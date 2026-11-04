"""Cadastro de OLTs contra o simulador (SNMP de verdade, UDP local)."""

from datetime import datetime, timedelta, timezone

import pytest

from lumio_api.routers.olts import collection_status

from .conftest import SERVICE_TOKEN, needs_db, olt_body, signup

pytestmark = needs_db


async def test_testar_conexao_detecta_fabricante_e_modelo(client, lab):
    headers = await signup(client)
    resp = await client.post("/api/olts/test-connection", headers=headers,
                             json={"host": "127.0.0.1", "snmp_port": lab.network.olt("olt-1").port,
                                   "community": "public"})
    assert resp.json() == {"ok": True, "vendor": "huawei", "model": "MA5800-X7", "sys_name": "olt-1",
                           "pon_ports": ["0/1/0", "0/1/1"], "onus": 16, "error": None}


async def test_testar_conexao_com_community_errada(client, lab):
    headers = await signup(client)
    resp = await client.post("/api/olts/test-connection", headers=headers,
                             json={"host": "127.0.0.1", "snmp_port": lab.network.olt("olt-1").port,
                                   "community": "errada"})
    body = resp.json()
    assert resp.status_code == 200 and body["ok"] is False
    assert "community" in body["error"]


async def test_cadastrar_descobre_portas_e_onus(client, lab, pool):
    headers = await signup(client)
    resp = await client.post("/api/olts", headers=headers, json=olt_body(lab, status_interval_s=120))
    assert resp.status_code == 201, resp.text
    saved = resp.json()
    assert saved["discovery"] == {"ok": True, "pon_ports": 2, "onus": 16, "onus_online": 16, "error": None}
    olt = saved["olt"]
    assert (olt["vendor"], olt["model"], olt["sys_name"]) == ("huawei", "MA5800-X7", "olt-1")
    # estado online fica para a 1ª coleta (worker): até lá, 0 online e "Aguardando 1ª coleta"
    assert (olt["pon_ports"], olt["onus_total"], olt["onus_online"]) == (2, 16, 0)
    assert olt["status_interval_s"] == 120 and olt["collection_status"] == "pending"
    assert olt["has_community"] is True and "community" not in olt

    serials = {r["serial"] for r in await pool.fetch("SELECT serial FROM onus")}
    real = {u.serial for p in lab.network.olt("olt-1").pons.values() for u in p.onus.values()}
    assert serials == real


async def test_community_fica_cifrada_no_banco(client, lab, pool):
    headers = await signup(client)
    await client.post("/api/olts", headers=headers, json=olt_body(lab, community="public"))
    stored = await pool.fetchval("SELECT community_enc FROM olts")
    assert stored and "public" not in stored


async def test_olt_fora_do_ar_e_salva_mesmo_assim(client, lab):
    headers = await signup(client)
    await lab.scenario("olt_down", olt="olt-1")
    resp = await client.post("/api/olts", headers=headers, json=olt_body(lab))
    assert resp.status_code == 201
    assert resp.json()["discovery"]["ok"] is False
    assert resp.json()["olt"]["last_error"]


async def test_endereco_que_nao_existe_e_sem_resposta_nao_erro_500(client, lab):
    """Nome que não resolve no DNS (erro de digitação, ou "simulator" visto da Vercel)."""
    headers = await signup(client)
    body = {**olt_body(lab), "host": "olt-que-nao-existe.invalid"}
    test = await client.post("/api/olts/test-connection", headers=headers,
                             json={k: body[k] for k in ("host", "snmp_port", "community")})
    assert test.status_code == 200 and test.json()["ok"] is False
    assert "não encontrado" in test.json()["error"]
    resp = await client.post("/api/olts", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["discovery"]["ok"] is False


async def test_lista_mostra_uso_do_plano_e_bloqueia_excesso(client, lab):
    headers = await signup(client)
    for name in ("olt-1", "olt-2"):
        assert (await client.post("/api/olts", headers=headers, json=olt_body(lab, name))).status_code == 201
    listing = (await client.get("/api/olts", headers=headers)).json()
    assert listing["usage"] == {"used": 2, "limit": 2}
    assert [o["name"] for o in listing["items"]] == ["olt-1", "olt-2"]

    extra = await client.post("/api/olts", headers=headers, json=olt_body(lab, "olt-1", name="olt-3"))
    assert extra.status_code == 403
    assert "2 de 2" in extra.json()["detail"]


async def test_nome_repetido(client, lab):
    headers = await signup(client)
    await client.post("/api/olts", headers=headers, json=olt_body(lab))
    assert (await client.post("/api/olts", headers=headers, json=olt_body(lab, "olt-2", name="olt-1"))).status_code == 409


@pytest.mark.parametrize("field, value", [
    ("status_interval_s", 5), ("optical_interval_s", 10), ("snmp_port", 70000), ("host", "10.0.0 .1"), ("community", ""),
])
async def test_validacao_do_formulario(client, lab, field, value):
    headers = await signup(client)
    assert (await client.post("/api/olts", headers=headers, json=olt_body(lab, **{field: value}))).status_code == 422


async def test_alterar_e_remover(client, lab, pool):
    headers = await signup(client)
    olt_id = (await client.post("/api/olts", headers=headers, json=olt_body(lab))).json()["olt"]["id"]

    renamed = await client.patch(f"/api/olts/{olt_id}", headers=headers, json={"name": "Centro", "enabled": False})
    assert renamed.json()["olt"]["name"] == "Centro"
    assert renamed.json()["olt"]["collection_status"] == "disabled"

    # trocar o acesso SNMP refaz a descoberta (aqui, apontando para a outra OLT)
    moved = await client.patch(f"/api/olts/{olt_id}", headers=headers,
                               json={"snmp_port": lab.network.olt("olt-2").port})
    assert moved.json()["discovery"]["ok"] is True
    assert moved.json()["olt"]["sys_name"] == "olt-2"

    assert (await client.delete(f"/api/olts/{olt_id}", headers=headers)).status_code == 204
    assert (await client.get(f"/api/olts/{olt_id}", headers=headers)).status_code == 404
    assert await pool.fetchval("SELECT count(*) FROM onus") == 0          # cascata


async def test_testar_conexao_de_olt_salva_usa_a_community_guardada(client, lab):
    headers = await signup(client)
    olt_id = (await client.post("/api/olts", headers=headers, json=olt_body(lab))).json()["olt"]["id"]
    resp = await client.post(f"/api/olts/{olt_id}/test-connection", headers=headers)
    assert resp.json()["ok"] is True


async def test_operador_nao_altera_cadastro(client, lab, pool):
    headers = await signup(client)
    await pool.execute("UPDATE users SET role = 'operator'")
    login = await client.post("/api/auth/login", json={"email": "admin@a.com.br", "password": "senha-forte-123"})
    op = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/olts", headers=op)).status_code == 200
    assert (await client.post("/api/olts", headers=op, json=olt_body(lab))).status_code == 403


async def test_rota_interna_do_coletor(client, lab):
    headers = await signup(client)
    await client.post("/api/olts", headers=headers, json=olt_body(lab))
    await client.post("/api/olts", headers=headers, json=olt_body(lab, "olt-2", enabled=False))

    assert (await client.get("/api/internal/collector/olts")).status_code == 401
    assert (await client.get("/api/internal/collector/olts", headers=headers)).status_code == 401   # JWT não vale
    resp = await client.get("/api/internal/collector/olts", headers={"X-Service-Token": SERVICE_TOKEN})
    [olt] = resp.json()                                   # a desativada não vai para o coletor
    assert (olt["name"], olt["community"], olt["sys_name"]) == ("olt-1", "public", "olt-1")


def test_status_da_coleta():
    now = datetime.now(timezone.utc)
    base = {"enabled": True, "reachable": True, "last_poll_at": now - timedelta(seconds=30), "status_interval_s": 60}
    assert collection_status(base, now) == "ok"
    assert collection_status({**base, "last_poll_at": None, "reachable": None}, now) == "pending"
    assert collection_status({**base, "last_poll_at": now - timedelta(minutes=10)}, now) == "late"
    assert collection_status({**base, "reachable": False}, now) == "error"
    assert collection_status({**base, "enabled": False, "reachable": False}, now) == "disabled"
