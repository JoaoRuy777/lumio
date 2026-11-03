"""Critério de pronto da sprint 2, de ponta a ponta:

falha no simulador -> trap -> coletor -> Redis Stream -> worker -> alarme no Postgres,
com a latência medida e registrada.
"""

import asyncio
import time
import uuid

import pytest
import redis.asyncio as redis

from lumio_collector.sink import RedisStreamSink
from lumio_worker.consumer import Consumer
from lumio_worker.processor import Processor

from ..conftest import Lab
from .conftest import REDIS_URL, needs_redis

pytestmark = needs_redis


@pytest.fixture
async def pipeline(pool):
    stream = f"test:{uuid.uuid4().hex[:8]}"
    lab = Lab()
    sink = RedisStreamSink(REDIS_URL, stream=stream)
    for w in lab.workers:
        w.sink = sink
    r = redis.from_url(REDIS_URL, decode_responses=True)
    processor = Processor(pool)
    await processor.setup()
    consumer = Consumer(r, processor, stream=stream, block_ms=100)
    await consumer.ensure_group()
    task = asyncio.create_task(consumer.run())
    await lab.start()
    yield lab, pool, consumer
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    lab.close()
    await r.delete(stream, consumer.dead_letter)
    await r.aclose()
    await sink.redis.aclose()


async def wait_for(check, timeout=5.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if await check():
            return True
        await asyncio.sleep(0.02)
    return await check()


async def test_rompimento_no_simulador_vira_alarme_no_banco(pipeline):
    lab, pool, consumer = pipeline
    # inventário da primeira coleta (2 OLTs x 2 PONs x 8 ONUs)
    assert await wait_for(count_is(pool, "SELECT count(*) FROM onus WHERE online", 32))

    t0 = time.perf_counter()
    await lab.scenario("fiber_cut", olt="olt-2", pon="0/1/1")
    assert await wait_for(count_is(pool, "SELECT count(*) FROM alarms WHERE kind = 'pon_fiber_cut'", 1))
    latency_ms = (time.perf_counter() - t0) * 1000

    cut = await pool.fetchrow(
        "SELECT a.*, p.name AS pon, o.name AS olt FROM alarms a "
        "JOIN pon_ports p ON p.id = a.pon_id JOIN olts o ON o.id = a.olt_id WHERE kind = 'pon_fiber_cut'")
    assert (cut["olt"], cut["pon"], cut["severity"], cut["source"]) == ("olt-2", "0/1/1", "critical", "trap")
    assert cut["latency_ms"] is not None and 0 <= cut["latency_ms"] < 1000
    assert await pool.fetchval("SELECT count(*) FROM alarms WHERE parent_id = $1", cut["id"]) == 8
    assert latency_ms < 2000
    assert consumer.failed == 0
    print(f"\nlatência falha no simulador -> alarme no banco: {latency_ms:.0f} ms "
          f"(coletor -> banco: {cut['latency_ms']:.0f} ms)")


async def test_olt_fora_do_ar_vira_alarme_pelo_polling(pipeline):
    lab, pool, _ = pipeline
    await lab.scenario("olt_down", olt="olt-1")
    w = lab.workers[0]
    await w.run_once(w.collect_status)
    assert await wait_for(count_is(pool, "SELECT count(*) FROM alarms WHERE kind = 'olt_unreachable' "
                                         "AND status = 'active'", 1))
    await lab.scenario("reset", olt="olt-1")
    await w.run_once(w.collect_status)
    assert await wait_for(count_is(pool, "SELECT count(*) FROM alarms WHERE kind = 'olt_unreachable' "
                                         "AND status = 'cleared'", 1))


def count_is(pool, sql, expected):
    async def check():
        return await pool.fetchval(sql) == expected
    return check
