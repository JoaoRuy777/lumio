"""Página pública de status: só bairros, nada de dado de cliente, e desligada até o admin ligar."""

from datetime import datetime, timedelta, timezone

import pytest

from .conftest import needs_db, signup

pytestmark = needs_db


@pytest.fixture
async def rede(client, pool):
    """Provedor com 1 OLT e 2 PONs: PON A atende Centro e Vila Nova, PON B atende Jardim."""
    h = await signup(client, company="Fibra Sul", email="admin@fibrasul.com.br")
    tid = await pool.fetchval("SELECT id FROM tenants")
    olt = await pool.fetchval("INSERT INTO olts (tenant_id, name, host) VALUES ($1, 'HW-CENTRO-01', '10.0.0.1') RETURNING id", tid)
    pons = {}
    for name, clientes in {"0/1/0": [("Ana Souza", "Centro"), ("Bruno Lima", "Vila Nova")],
                           "0/1/1": [("Carla Dias", "Jardim"), ("Davi Rocha", "")]}.items():
        pons[name] = await pool.fetchval(
            "INSERT INTO pon_ports (tenant_id, olt_id, name) VALUES ($1, $2, $3) RETURNING id", tid, olt, name)
        for i, (cliente, bairro) in enumerate(clientes):
            serial = f"HWTC{name[-1]}{i:07d}"
            await pool.execute("INSERT INTO onus (tenant_id, olt_id, pon_id, onu_index, serial, online) "
                               "VALUES ($1, $2, $3, $4, $5, false)", tid, olt, pons[name], i, serial)
            await pool.execute("INSERT INTO customers (tenant_id, onu_serial, name, phone, district) "
                               "VALUES ($1, $2, $3, '14 99999-0000', $4)", tid, serial, cliente, bairro)

    async def alarm(kind, pon=None, start=None, end=None):
        start = start or datetime.now(timezone.utc) - timedelta(minutes=20)
        await pool.execute(
            "INSERT INTO alarms (tenant_id, olt_id, pon_id, kind, severity, dedup_key, source, status, "
            "event_ts, first_seen_at, last_seen_at, cleared_at) "
            "VALUES ($1, $2, $3, $4, 'critical', gen_random_uuid()::text, 'trap', $5, $6, $6, $6, $7)",
            tid, olt, pon and pons[pon], kind, "cleared" if end else "active", start, end)

    return {"h": h, "tid": tid, "olt": olt, "pons": pons, "alarm": alarm}


async def ligar(client, h, slug="fibrasul", enabled=True):
    return await client.put("/api/status-page", headers=h, json={"enabled": enabled, "slug": slug})


async def test_comeca_desligada_e_responde_404_igual_a_inexistente(client, rede):
    cfg = (await client.get("/api/status-page", headers=rede["h"])).json()
    assert cfg["enabled"] is False and cfg["slug"].startswith("fibra-sul-")
    desligada = await client.get(f"/api/public/status/{cfg['slug']}")
    inexistente = await client.get("/api/public/status/nao-existe")
    assert desligada.status_code == inexistente.status_code == 404
    assert desligada.json() == inexistente.json()


async def test_rede_normal(client, rede):
    assert (await ligar(client, rede["h"])).json() == {"enabled": True, "slug": "fibrasul"}
    r = await client.get("/api/public/status/fibrasul")        # sem login
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=30, s-maxage=30"
    body = r.json()
    assert body["name"] == "Fibra Sul"
    assert body["incidents"] == body["maintenance"] == body["history"] == []


async def test_rompimento_mostra_so_os_bairros(client, rede, pool):
    await ligar(client, rede["h"])
    await rede["alarm"]("pon_fiber_cut", pon="0/1/0")
    await rede["alarm"]("onu_offline", pon="0/1/1")              # ONU sozinha: assunto interno, não aparece
    ontem = datetime.now(timezone.utc) - timedelta(days=1)
    await rede["alarm"]("olt_unreachable", start=ontem, end=ontem + timedelta(minutes=12))
    r = await client.get("/api/public/status/FibraSul")
    body = r.json()
    [inc] = body["incidents"]
    assert inc["kind"] == "pon_fiber_cut" and inc["districts"] == ["Centro", "Vila Nova"]
    [hist] = body["history"]
    assert hist["kind"] == "olt_unreachable" and hist["districts"] == ["Centro", "Jardim", "Vila Nova"]
    # nada de dado de cliente nem da rede interna
    for segredo in ("Ana", "Bruno", "Carla", "99999", "HW-CENTRO", "10.0.0.1", "0/1/0", "HWTC"):
        assert segredo not in r.text


async def test_manutencao_aparece_sem_o_motivo(client, rede, pool):
    await ligar(client, rede["h"])
    now = datetime.now(timezone.utc)
    await pool.execute(
        "INSERT INTO maintenance_windows (tenant_id, olt_id, pon_id, reason, starts_at, ends_at) "
        "VALUES ($1, $2, $3, 'Troca do splitter da Rua 7 (motivo interno)', $4, $5)",
        rede["tid"], rede["olt"], rede["pons"]["0/1/1"], now + timedelta(hours=2), now + timedelta(hours=4))
    r = await client.get("/api/public/status/fibrasul")
    [m] = r.json()["maintenance"]
    assert m["in_progress"] is False and m["districts"] == ["Jardim"]
    assert "splitter" not in r.text


async def test_endereco_invalido_repetido_e_so_admin(client, rede):
    assert (await ligar(client, rede["h"], slug="Com Espaço")).status_code == 422
    assert (await ligar(client, rede["h"], slug="-x")).status_code == 422
    outro = await signup(client, company="Outro", email="admin@outro.com.br")
    assert (await ligar(client, outro, slug="fibrasul")).status_code == 200
    assert (await ligar(client, rede["h"], slug="fibrasul")).status_code == 409

    operador = await client.post("/api/users", headers=rede["h"], json={
        "name": "Op", "email": "op@fibrasul.com.br", "password": "senha-forte-123", "role": "operator"})
    assert operador.status_code == 201, operador.text
    login = await client.post("/api/auth/login", json={"email": "op@fibrasul.com.br", "password": "senha-forte-123"})
    hop = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await ligar(client, hop, slug="op-tentou")).status_code == 403


async def test_alteracao_fica_na_auditoria(client, rede):
    await ligar(client, rede["h"])
    audit = (await client.get("/api/audit-log", headers=rede["h"], params={"category": "status_page"})).json()
    [e] = audit["items"]
    assert e["action_label"] == "Alterou a página pública de status" and e["details"]["slug"] == "fibrasul"
