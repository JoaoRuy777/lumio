"""Agendador de coleta: um conjunto de laços por OLT.

- estado das ONUs e saúde da OLT a cada 60 s
- potência óptica a cada 5 min
- no máximo uma consulta por vez em cada OLT, para não sobrecarregar o equipamento
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .sink import Sink
from .snmp import SnmpClient, SnmpError, Target
from .vendors import DRIVERS, Driver, detect

log = logging.getLogger("lumio_collector.poller")

SYS_OBJECT_ID = (1, 3, 6, 1, 2, 1, 1, 2, 0)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class OltConfig:
    name: str
    host: str
    port: int = 161
    community: str = "public"
    vendor: str | None = None          # None = detecta pelo sysObjectID
    status_interval: float = 60
    optical_interval: float = 300
    timeout: float = 2.0
    retries: int = 1

    @property
    def target(self) -> Target:
        return Target(self.host, self.port, self.community, self.timeout, self.retries)


async def probe(client: SnmpClient, target: Target) -> dict:
    """O que o botão "Testar conexão" vai chamar: identifica a OLT e conta portas e ONUs."""
    sys_oid = (await client.get(target, SYS_OBJECT_ID))[SYS_OBJECT_ID]
    driver = detect(tuple(sys_oid))
    if driver is None:
        return {"ok": False, "error": f"fabricante não suportado (sysObjectID {sys_oid.prettyPrint()})"}
    info = await driver.info(client, target)
    return {"ok": True, **asdict(info)}


class OltWorker:
    def __init__(self, cfg: OltConfig, client: SnmpClient, sink: Sink):
        self.cfg = cfg
        self.client = client
        self.sink = sink
        self.driver: Driver | None = DRIVERS.get(cfg.vendor) if cfg.vendor else None
        self.sys_name: str | None = None
        self.reachable: bool | None = None
        self.lock = asyncio.Lock()
        self.tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------- envio

    async def emit(self, type_: str, **data) -> None:
        await self.sink.publish({"type": type_, "olt": self.cfg.name, "ts": now(), **data})

    async def _set_reachable(self, ok: bool, error: str | None = None) -> None:
        if ok == self.reachable:
            return
        first = self.reachable is None
        self.reachable = ok
        if not ok:
            log.warning("%s sem resposta: %s", self.cfg.name, error)
            await self.emit("event", kind="olt_unreachable", source="poll", error=error)
        elif not first:
            log.info("%s voltou a responder", self.cfg.name)
            await self.emit("event", kind="olt_reachable", source="poll")

    # ------------------------------------------------------------- coleta

    async def _ensure_driver(self) -> Driver:
        if self.driver is None:
            sys_oid = (await self.client.get(self.cfg.target, SYS_OBJECT_ID))[SYS_OBJECT_ID]
            self.driver = detect(tuple(sys_oid))
            if self.driver is None:
                raise SnmpError(f"fabricante não suportado: {sys_oid.prettyPrint()}")
        if self.sys_name is None:
            info = await self.driver.info(self.client, self.cfg.target)
            self.sys_name = info.sys_name
            await self.emit("olt_info", **asdict(info))
        return self.driver

    async def collect_status(self) -> None:
        driver = await self._ensure_driver()
        t0 = time.perf_counter()
        onus = await driver.onu_status(self.client, self.cfg.target)
        health = await driver.health(self.client, self.cfg.target)
        await self.emit("onu_status", took_ms=round((time.perf_counter() - t0) * 1000), onus=[asdict(o) for o in onus])
        await self.emit("olt_health", **asdict(health))

    async def collect_optical(self) -> None:
        driver = await self._ensure_driver()
        t0 = time.perf_counter()
        readings = await driver.onu_optical(self.client, self.cfg.target)
        await self.emit("onu_optical", took_ms=round((time.perf_counter() - t0) * 1000), onus=[asdict(r) for r in readings])

    async def run_once(self, job) -> None:
        async with self.lock:
            try:
                await job()
            except SnmpError as e:
                await self._set_reachable(False, str(e))
            else:
                await self._set_reachable(True)

    async def _loop(self, job, interval: float) -> None:
        while True:
            start = time.monotonic()
            await self.run_once(job)
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - start)))

    def start(self) -> None:
        self.tasks = [
            asyncio.create_task(self._loop(self.collect_status, self.cfg.status_interval)),
            asyncio.create_task(self._loop(self.collect_optical, self.cfg.optical_interval)),
        ]

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
