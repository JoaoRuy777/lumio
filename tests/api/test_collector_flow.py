"""Fluxo completo da sprint 3:

OLT cadastrada na API -> coletor lê o cadastro -> falha no simulador ->
trap -> Redis -> worker -> alarme no tenant certo, visível na API.
"""

import asyncio
import time
import uuid

import httpx
import pytest
import redis.asyncio as redis

from lumio_collector.registry import ApiRegistry
from lumio_collector.sink import MemorySink, RedisStreamSink
from lumio_worker.consumer import Consumer
from lumio_worker.processor import Processor

from .conftest import SERVICE_TOKEN, olt_body, signup
from tests.db_fixtures import REDIS_URL, needs_redis

pytestmark = needs_redis


def registry_for(app, lab, sink) -> ApiRegistry:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lumio.test")
    return ApiRegistry("http://lumio.test", SERVICE_TOKEN, lab.client, sink, lab.receiver, http=http)


async def test_coletor_segue_o_cadastro(app, client, lab):
    headers = await signup(client)
    sink = MemorySink()
    registry = registry_for(app, lab, sink)
    try:
        olt_id = (await client.post("/api/olts", headers=headers, json=olt_body(lab, name="Centro"))).json()["olt"]["id"]
        assert await registry.sync_once()
        [w] = registry.workers.values()
        await w.run_once(w.collect_status)
        rec = sink.of("onu_status")[0]
        assert (rec["olt"], rec["olt_id"]) == ("Centro", olt_id)
        assert rec["tenant_id"]

        # a trap chega mesmo com nome cadastrado diferente do sysName da OLT
        await lab.scenario("onu_down", olt="olt-1", pon="0/1/0", onu=3)
        assert await lab.wait_for(lambda: sink.of("event", kind="onu_offline", olt_id=olt_id))

        # desativou no cadastro: o coletor para
        await client.patch(f"/api/olts/{olt_id}", headers=headers, json={"enabled": False})
        await registry.sync_once()
        assert registry.workers == {}
        assert lab.receiver.workers == []
    finally:
        await registry.close()


async def test_api_fora_do_ar_mantem_a_coleta(app, client, lab):
    headers = await signup(client)
    await client.post("/api/olts", headers=headers, json=olt_body(lab))
    registry = registry_for(app, lab, MemorySink())
    try:
        assert await registry.sync_once()
        registry.token = "token-errado"                    # simula falha ao ler o cadastro
        assert not await registry.sync_once()
        assert len(registry.workers) == 1
    finally:
        await registry.close()


@pytest.fixture
async def worker(pool):
    stream = f"test:{uuid.uuid4().hex[:8]}"
    r = redis.from_url(REDIS_URL, decode_responses=True)
    consumer = Consumer(r, Processor(pool), stream=stream, block_ms=100)
    await consumer.ensure_group()
    task = asyncio.create_task(consumer.run())
    yield consumer
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await r.delete(stream, consumer.dead_letter)
    await r.aclose()


async def test_falha_vira_alarme_do_provedor_certo(app, client, lab, pool, worker):
    a = await signup(client, company="Provedor A", email="admin@a.com.br")
    b = await signup(client, company="Provedor B", email="admin@b.com.br")
    olt_a = (await client.post("/api/olts", headers=a, json=olt_body(lab, "olt-2"))).json()["olt"]["id"]
    await client.post("/api/olts", headers=b, json=olt_body(lab, "olt-1"))

    sink = RedisStreamSink(REDIS_URL, stream=worker.stream)
    registry = registry_for(app, lab, sink)
    try:
        await registry.sync_once()
        t0 = time.perf_counter()
        await lab.scenario("fiber_cut", olt="olt-2", pon="0/1/1")

        async def alarm_visible():
            items = (await client.get("/api/olts", headers=a)).json()["items"]
            return items[0]["active_alarms"] == 9           # 1 rompimento + 8 ONUs
        for _ in range(250):
            if await alarm_visible():
                break
            await asyncio.sleep(0.02)
        assert await alarm_visible()
        print(f"\nlatência falha -> alarme visível na API: {(time.perf_counter() - t0) * 1000:.0f} ms")

        cut = await pool.fetchrow("SELECT a.*, t.name AS tenant FROM alarms a JOIN tenants t ON t.id = a.tenant_id "
                                  "WHERE kind = 'pon_fiber_cut'")
        assert (cut["tenant"], str(cut["olt_id"])) == ("Provedor A", olt_a)
        items_b = (await client.get("/api/olts", headers=b)).json()["items"]
        assert items_b[0]["active_alarms"] == 0
        assert worker.failed == 0
        # nenhum tenant "demo" foi criado: tudo veio com olt_id
        assert await pool.fetchval("SELECT count(*) FROM tenants") == 2
    finally:
        await registry.close()
        await sink.redis.aclose()


async def test_onu_ja_offline_no_cadastro_gera_alarme_na_primeira_coleta(app, client, lab, pool, worker):
    """Regressão: a descoberta não pode gravar o estado online, senão uma ONU
    que já estava offline no cadastro nunca vira alarme (sem transição)."""
    await lab.scenario("onu_down", olt="olt-1", pon="0/1/0", onu=5)
    headers = await signup(client)
    saved = (await client.post("/api/olts", headers=headers, json=olt_body(lab))).json()
    assert saved["discovery"]["onus_online"] == 15

    sink = RedisStreamSink(REDIS_URL, stream=worker.stream)
    registry = registry_for(app, lab, sink)
    try:
        await registry.sync_once()
        [w] = registry.workers.values()
        await w.run_once(w.collect_status)

        async def alarm_opened():
            return await pool.fetchval("SELECT count(*) FROM alarms a JOIN onus o ON o.id = a.onu_id "
                                       "WHERE a.kind = 'onu_offline' AND o.onu_index = 5") == 1
        for _ in range(100):
            if await alarm_opened():
                break
            await asyncio.sleep(0.02)
        assert await alarm_opened()
        olt = (await client.get("/api/olts", headers=headers)).json()["items"][0]
        assert (olt["onus_online"], olt["active_alarms"]) == (15, 1)
    finally:
        await registry.close()
        await sink.redis.aclose()
