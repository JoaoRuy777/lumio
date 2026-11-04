"""Tempo real (SSE): cada provedor recebe só os próprios avisos.

O transporte ASGI do httpx não faz streaming, então aqui a API roda num
uvicorn de verdade, numa porta livre.
"""

import asyncio
import json
import socket
import uuid

import httpx
import pytest
import redis.asyncio as redis
import uvicorn

from lumio_api.main import create_app
from lumio_worker.processor import Processor

from tests.db_fixtures import REDIS_URL, needs_redis

from .conftest import olt_body, signup

pytestmark = needs_redis


def free_tcp_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def server(settings, pool):
    from dataclasses import replace

    app = create_app(replace(settings, redis_url=REDIS_URL))
    port = free_tcp_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.02)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
        yield client
    srv.should_exit = True
    await task


class Stream:
    """Lê eventos SSE em segundo plano."""

    def __init__(self, client, headers):
        self.events: list[dict] = []
        self.ready = asyncio.Event()
        self.task = asyncio.create_task(self._run(client, headers))

    async def _run(self, client, headers):
        async with client.stream("GET", "/api/events", headers=headers) as resp:
            assert resp.headers["content-type"].startswith("text/event-stream")
            event = "message"                       # nome padrão do SSE
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    if event == "ready":
                        self.ready.set()
                    else:
                        self.events.append(json.loads(line[6:]))
                elif line == "":                    # linha vazia fecha o evento
                    event = "message"

    async def wait_for(self, n, timeout=3.0):
        for _ in range(int(timeout / 0.02)):
            if len(self.events) >= n:
                return self.events
            await asyncio.sleep(0.02)
        return self.events

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def test_sse_exige_login(server):
    assert (await server.get("/api/events")).status_code == 401


async def test_cada_provedor_recebe_so_os_proprios_avisos(server, lab, pool):
    a = await signup(server, company="Provedor A", email="admin@a.com.br")
    b = await signup(server, company="Provedor B", email="admin@b.com.br")
    olt_a = (await server.post("/api/olts", headers=a, json=olt_body(lab))).json()["olt"]["id"]
    tenant_a = await pool.fetchval("SELECT tenant_id FROM olts WHERE id = $1", uuid.UUID(olt_a))

    stream_a, stream_b = Stream(server, a), Stream(server, b)
    await asyncio.wait_for(asyncio.gather(stream_a.ready.wait(), stream_b.ready.wait()), 3)
    r = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        # o worker grava o alarme e avisa o canal do provedor A
        processor = Processor(pool, redis=r)
        await processor.handle({"type": "event", "olt": "olt-1", "olt_id": olt_a, "tenant_id": str(tenant_a),
                                "ts": "2026-11-04T12:00:00+00:00", "kind": "olt_unreachable", "source": "poll"})
        [opened] = await stream_a.wait_for(1)
        assert (opened["type"], opened["kind"], opened["severity"]) == ("alarm.opened", "olt_unreachable", "critical")

        # reconhecer pela API também avisa (depois do commit)
        assert (await server.post(f"/api/alarms/{opened['alarm_id']}/ack", headers=a)).status_code == 200
        events = await stream_a.wait_for(2)
        assert events[1] == {"type": "alarm.acknowledged", "alarm_id": opened["alarm_id"]}

        await asyncio.sleep(0.2)
        assert stream_b.events == []          # o provedor B não ouviu nada
    finally:
        await stream_a.close()
        await stream_b.close()
        await r.aclose()
