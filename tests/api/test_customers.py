"""Clientes (CSV), mapa da rede e ONUs com sinal piorando."""

from datetime import datetime, timedelta, timezone

from .conftest import needs_db, signup
from .test_dashboard import get, net  # noqa: F401

pytestmark = needs_db


async def serials(client, net):
    onus = (await get(client, net, "/onus", limit=200))["items"]
    return {(o["pon"], o["onu_index"]): o for o in onus}


async def test_importa_csv_com_ponto_e_virgula_e_atualiza(client, net):
    onus = await serials(client, net)
    a, b = onus[("0/1/0", 0)], onus[("0/1/1", 3)]
    csv = ("﻿Serial;Nome;Telefone;Endereço;Bairro;Cidade;Plano;Latitude;Longitude\n"
           f"{a['serial'].lower()};Maria Souza;(14) 99999-0000;Rua A, 10;Centro;Marília;500 Mega;-22,2140;-49,9460\n"
           f"{b['serial']};João Lima;;Rua B, 20;Fragata;Marília;;-22.215;-49.947\n"
           ";Sem serial;;;;;;;\n"
           "HWTCNAOEXISTE;Fantasma;;;;;;-22.2;-49.9\n"
           "HWTCX;Coordenada ruim;;;;;;-122;0\n")
    resp = await client.post("/api/customers/import", headers=net["headers"], json={"csv": csv})
    assert resp.status_code == 200, resp.text
    r = resp.json()
    assert (r["created"], r["updated"], r["unmatched"]) == (3, 0, 1)
    assert [e["line"] for e in r["errors"]] == [4, 6]

    again = await client.post("/api/customers/import", headers=net["headers"],
                              json={"csv": f"serial,nome\n{a['serial']},Maria Souza Lima\n"})
    assert (again.json()["created"], again.json()["updated"]) == (0, 1)

    page = await get(client, net, "/customers", q="maria")
    [maria] = page["items"]
    assert (maria["name"], maria["onu_id"], maria["pon"], maria["state"]) == ("Maria Souza Lima", a["id"], "0/1/0", "online")
    assert (await get(client, net, "/customers", state="unknown"))["total"] == 1     # o fantasma
    customer = (await client.get(f"/api/onus/{a['id']}/customer", headers=net["headers"])).json()
    assert customer["name"] == "Maria Souza Lima"


async def test_csv_sem_colunas_obrigatorias(client, net):
    resp = await client.post("/api/customers/import", headers=net["headers"], json={"csv": "nome;telefone\nX;1\n"})
    assert resp.status_code == 422 and "serial e nome" in resp.json()["detail"]


async def test_rompimento_mostra_clientes_e_mapa(client, net):
    onus = await serials(client, net)
    lines = [f"{o['serial']};Cliente {pon} {idx};-22.21{idx};-49.94{idx}" for (pon, idx), o in onus.items()]
    await client.post("/api/customers/import", headers=net["headers"],
                      json={"csv": "serial;nome;latitude;longitude\n" + "\n".join(lines)})
    await net["fiber_cut"]()
    [cut] = (await get(client, net, "/alarms"))["items"]
    assert cut["affected_customers"] == 8
    assert (await get(client, net, "/overview"))["customers_offline"] == 8
    [child] = (await get(client, net, "/alarms", parent_id=cut["id"], limit=1))["items"]
    assert child["customer_name"].startswith("Cliente 0/1/1")

    m = await get(client, net, "/map")
    [olt] = m["olts"]
    assert olt["located"] is False and olt["lat"] is not None          # centro dos clientes
    states = {c["pon"]: set() for c in m["customers"]}
    for c in m["customers"]:
        states[c["pon"]].add(c["state"])
    assert states == {"0/1/0": {"online"}, "0/1/1": {"offline"}}
    assert {c["ticket_id"] for c in m["customers"] if c["pon"] == "0/1/1"} == {cut["id"]}

    # localização da OLT pelo cadastro
    await client.patch(f"/api/olts/{net['olt_id']}", headers=net["headers"], json={"lat": -22.2, "lon": -49.9})
    [olt] = (await get(client, net, "/map"))["olts"]
    assert (olt["lat"], olt["lon"], olt["located"]) == (-22.2, -49.9, True)


async def test_outro_provedor_nao_ve_clientes(client, net):
    onus = await serials(client, net)
    a = next(iter(onus.values()))
    await client.post("/api/customers/import", headers=net["headers"], json={"csv": f"serial;nome\n{a['serial']};Maria\n"})
    other = await signup(client, company="Provedor B", email="admin@b.com.br")
    assert (await client.get("/api/customers", headers=other)).json()["total"] == 0
    assert (await client.get("/api/map", headers=other)).json()["customers"] == []


async def test_sinal_piorando(client, net, pool):
    onus = await serials(client, net)
    falling, steady = onus[("0/1/0", 1)], onus[("0/1/0", 2)]
    now = datetime.now(timezone.utc)
    tenant = await pool.fetchval("SELECT tenant_id FROM onus WHERE id = $1", falling["id"])
    await pool.execute("DELETE FROM optical_readings")
    for k in range(12):                         # 1 h de leituras, a cada 5 min
        ts = now - timedelta(minutes=5 * (11 - k))
        await pool.execute("INSERT INTO optical_readings (ts, tenant_id, onu_id, rx_dbm) VALUES ($1, $2, $3, $4)",
                           ts, tenant, falling["id"], -20.0 - 0.05 * k)        # -0,6 dB/h = -14,4 dB/dia
        await pool.execute("INSERT INTO optical_readings (ts, tenant_id, onu_id, rx_dbm) VALUES ($1, $2, $3, $4)",
                           ts, tenant, steady["id"], -20.0 + (0.01 if k % 2 else -0.01))
    await pool.execute("UPDATE onus SET rx_dbm = -20.55 WHERE id = $1", falling["id"])
    await pool.execute("UPDATE onus SET rx_dbm = -20.0 WHERE id = $1", steady["id"])

    [risk] = await get(client, net, "/onus-at-risk")
    assert risk["onu_id"] == falling["id"]
    assert risk["slope_db_day"] == -14.4
    assert 0.4 < risk["days_to_limit"] < 0.5                 # (-20,55 + 27) / 14,4 ≈ 0,45 dia
    assert (await get(client, net, "/overview"))["rx_trend"] == 1
