"""Rotas do painel (sprint 4): visão geral, PONs, ONUs, histórico e alarmes.

Os dados vêm do caminho real: simulador -> coletor (SNMP e traps) -> worker
-> Postgres. Para não depender de Redis aqui, o coletor entrega os registros
direto ao processador do worker.
"""

import asyncio

import httpx
import pytest

from lumio_collector.registry import ApiRegistry
from lumio_worker.processor import Processor

from .conftest import SERVICE_TOKEN, needs_db, olt_body, signup

pytestmark = needs_db


class ProcessorSink:
    """Sink do coletor que grava na hora pelo worker (sem fila)."""

    def __init__(self, processor: Processor):
        self.processor = processor
        self.lock = asyncio.Lock()          # o worker real processa um registro por vez

    async def publish(self, record: dict) -> None:
        async with self.lock:
            await self.processor.handle(record)


@pytest.fixture
async def net(app, client, lab, pool):
    """Provedor com a OLT olt-2 do simulador cadastrada e já coletada (2 PONs x 8 ONUs)."""
    headers = await signup(client)
    olt_id = (await client.post("/api/olts", headers=headers, json=olt_body(lab, "olt-2"))).json()["olt"]["id"]
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lumio.test")
    registry = ApiRegistry("http://lumio.test", SERVICE_TOKEN, lab.client, ProcessorSink(Processor(pool)),
                           lab.receiver, http=http)
    await registry.sync_once()
    [worker] = registry.workers.values()
    await worker.run_once(worker.collect_status)
    await worker.run_once(worker.collect_optical)

    async def fiber_cut():
        await lab.scenario("fiber_cut", olt="olt-2", pon="0/1/1")
        await wait(lambda: pool.fetchval("SELECT count(*) FROM alarms WHERE kind = 'pon_fiber_cut'"), 1)

    yield {"headers": headers, "olt_id": olt_id, "worker": worker, "fiber_cut": fiber_cut}
    await registry.close()


async def wait(query, expected, timeout=3.0):
    for _ in range(int(timeout / 0.02)):
        if await query() == expected:
            return
        await asyncio.sleep(0.02)
    assert await query() == expected


async def get(client, net, path, **params):
    resp = await client.get(f"/api{path}", headers=net["headers"], params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_visao_geral(client, net):
    ov = await get(client, net, "/overview")
    assert ov["olts"] == {"total": 1, "ok": 1, "error": 0, "late": 0, "pending": 0, "disabled": 0}
    assert ov["onus"] == {"total": 16, "online": 16, "offline": 0, "unknown": 0}
    assert ov["alarms"]["total"] == 0 and ov["recent_alarms"] == []

    await net["fiber_cut"]()
    ov = await get(client, net, "/overview")
    assert ov["onus"]["offline"] == 8
    # 1 alarme crítico, não 9: as ONUs ficam dentro do rompimento
    assert ov["alarms"] == {"critical": 1, "major": 0, "minor": 0, "warning": 0, "total": 1}
    [recent] = ov["recent_alarms"]
    assert (recent["kind"], recent["pon"], recent["children"]) == ("pon_fiber_cut", "0/1/1", 8)


async def test_pons_da_olt(client, net):
    await net["fiber_cut"]()
    pons = await get(client, net, f"/olts/{net['olt_id']}/pons")
    assert [(p["name"], p["onus_online"], p["onus_total"], p["active_alarms"]) for p in pons] == [
        ("0/1/0", 8, 8, 0), ("0/1/1", 0, 8, 1)]
    assert -30 < pons[0]["rx_avg"] < -15 and pons[1]["rx_avg"] is None


async def test_onus_com_filtros(client, net, lab):
    await net["fiber_cut"]()
    page = await get(client, net, "/onus")
    assert page["total"] == 16
    assert [o["online"] for o in page["items"][:8]] == [False] * 8         # offline primeiro
    assert page["items"][0]["active_alarms"] == ["onu_offline"]

    assert (await get(client, net, "/onus", status="offline"))["total"] == 8
    assert (await get(client, net, "/onus", status="online", limit=3))["total"] == 8
    assert len((await get(client, net, "/onus", status="online", limit=3))["items"]) == 3

    serial = lab.network.olt("olt-2").pon("0/1/0").onus[4].serial
    [found] = (await get(client, net, "/onus", q=serial[-6:].lower()))["items"]
    assert (found["serial"], found["pon"], found["onu_index"]) == (serial, "0/1/0", 4)
    assert (await get(client, net, f"/onus/{found['id']}"))["serial"] == serial


async def test_sinal_baixo_aparece_no_filtro_e_na_visao_geral(client, net, lab):
    await lab.scenario("degrade", olt="olt-2", pon="0/1/0", onu=2, rate_db_per_min=3, target_dbm=-31)
    for _ in range(15):
        lab.network.tick(minutes=1)
    w = net["worker"]
    await w.run_once(w.collect_optical)
    [low] = (await get(client, net, "/onus", rx_below=-27))["items"]
    assert low["onu_index"] == 2 and low["rx_dbm"] < -27 and "onu_rx_low" in low["active_alarms"]
    assert (await get(client, net, "/overview"))["rx_low"] == 1


async def test_historico_de_potencia(client, net):
    w = net["worker"]
    await w.run_once(w.collect_optical)
    onu = (await get(client, net, "/onus", limit=1))["items"][0]
    hist = await get(client, net, f"/onus/{onu['id']}/readings")
    # >= 2: além das duas chamadas acima, o laço de coleta do coletor também lê ao ligar
    assert hist["bucket_s"] == 0 and len(hist["items"]) >= 2
    assert all(-30 < r["rx_dbm"] < -15 for r in hist["items"])
    # 30 dias: médias por intervalo, no máximo ~300 pontos
    month = await get(client, net, f"/onus/{onu['id']}/readings", hours=720)
    # leituras de segundos atrás caem num intervalo só (ou em dois vizinhos, se cruzarem a fronteira)
    assert month["bucket_s"] == 720 * 3600 // 300 and 1 <= len(month["items"]) <= 2
    bad = await client.get(f"/api/onus/{onu['id']}/readings", headers=net["headers"], params={"hours": 0})
    assert bad.status_code == 422


async def test_alarmes_agrupados_filtros_e_historico(client, net, lab):
    await net["fiber_cut"]()
    page = await get(client, net, "/alarms")
    [cut] = page["items"]
    assert (cut["kind"], cut["severity"], cut["status"], cut["children"]) == ("pon_fiber_cut", "critical", "active", 8)
    assert cut["latency_ms"] is not None

    children = await get(client, net, "/alarms", parent_id=cut["id"])
    assert children["total"] == 8 and {c["kind"] for c in children["items"]} == {"onu_offline"}
    assert children["items"][0]["onu_serial"]

    assert (await get(client, net, "/alarms", severity="minor"))["total"] == 0      # filhos não contam
    assert (await get(client, net, "/alarms", severity=["critical", "major"]))["total"] == 1

    await lab.scenario("reset")
    await wait(lambda: _open_count(client, net), 0)
    history = await get(client, net, "/alarms", status="cleared")
    assert history["items"][0]["kind"] == "pon_fiber_cut" and history["items"][0]["cleared_at"]


async def _open_count(client, net):
    return (await get(client, net, "/alarms"))["total"]


async def test_reconhecer_alarme(client, net, pool):
    await net["fiber_cut"]()
    [cut] = (await get(client, net, "/alarms"))["items"]
    resp = await client.post(f"/api/alarms/{cut['id']}/ack", headers=net["headers"])
    assert resp.status_code == 200
    acked = resp.json()
    assert (acked["status"], acked["acknowledged_by"]) == ("acknowledged", "Admin")
    # reconhecido continua aberto, e as ONUs do rompimento vão junto
    assert (await get(client, net, "/alarms"))["total"] == 1
    children = (await get(client, net, "/alarms", parent_id=cut["id"]))["items"]
    assert {c["status"] for c in children} == {"acknowledged"}

    await pool.execute("UPDATE alarms SET status = 'cleared'")
    assert (await client.post(f"/api/alarms/{cut['id']}/ack", headers=net["headers"])).status_code == 409


async def test_operador_pode_reconhecer(client, net, pool):
    await net["fiber_cut"]()
    await pool.execute("UPDATE users SET role = 'operator'")
    login = await client.post("/api/auth/login", json={"email": "admin@a.com.br", "password": "senha-forte-123"})
    op = {"Authorization": f"Bearer {login.json()['access_token']}"}
    [cut] = (await client.get("/api/alarms", headers=op)).json()["items"]
    assert (await client.post(f"/api/alarms/{cut['id']}/ack", headers=op)).status_code == 200


async def test_historico_24h(client, net):
    h = (await get(client, net, "/overview/history"))["hours"]
    assert len(h) == 24 and all(p["open"] == 0 and p["onus_offline"] == 0 for p in h)

    await net["fiber_cut"]()
    h = (await get(client, net, "/overview/history"))["hours"]
    now = h[-1]
    # a hora atual: 1 alarme crítico aberto (o rompimento), 8 ONUs offline dentro dele
    assert (now["critical"], now["major"], now["other"], now["open"], now["onus_offline"]) == (1, 0, 0, 1, 8)
    assert h[0]["t"] < now["t"]

    ov = await get(client, net, "/overview")
    assert ov["customers_offline"] == 0          # sem clientes importados


async def test_historico_isolado_por_provedor(client, net):
    await net["fiber_cut"]()
    other = await signup(client, company="Provedor B", email="admin@b.com.br")
    resp = await client.get("/api/overview/history", headers=other)
    assert resp.status_code == 200
    assert all(p["open"] == 0 and p["onus_offline"] == 0 and p["critical"] == 0 for p in resp.json()["hours"])


async def test_chassi_da_olt(client, net, pool):
    olt = net["olt_id"]
    pons = (await get(client, net, f"/olts/{olt}/chassis"))
    assert [p["name"] for p in pons] == ["0/1/0", "0/1/1"]
    assert all(len(p["onus"]) == 8 and {o["state"] for o in p["onus"]} == {"online"} for p in pons)
    assert [o["onu_index"] for o in pons[0]["onus"]] == list(range(8))

    await net["fiber_cut"]()
    # uma ONU com sinal baixo na PON que segue no ar
    await pool.execute("UPDATE onus SET rx_dbm = -28.5 WHERE onu_index = 2 AND pon_id = $1", pons[0]["id"])
    pons = (await get(client, net, f"/olts/{olt}/chassis"))
    cut = next(p for p in pons if p["name"] == "0/1/1")
    ok = next(p for p in pons if p["name"] == "0/1/0")
    assert cut["fiber_cut"] is True and {o["state"] for o in cut["onus"]} == {"offline"}
    assert ok["fiber_cut"] is False and [o["state"] for o in ok["onus"]].count("low") == 1

    other = await signup(client, company="Provedor B", email="admin@b.com.br")
    assert (await client.get(f"/api/olts/{olt}/chassis", headers=other)).status_code == 404
