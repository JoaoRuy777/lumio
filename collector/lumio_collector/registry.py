"""Lista de OLTs vinda da API (sprint 3): o coletor consulta o cadastro a cada
30 s e liga, desliga ou reinicia a coleta das OLTs que mudaram."""

from __future__ import annotations

import asyncio
import logging

import httpx

from .poller import OltConfig, OltWorker
from .sink import Sink
from .snmp import SnmpClient
from .traps import TrapReceiver

log = logging.getLogger("lumio_collector.registry")


def config_from_api(item: dict) -> OltConfig:
    return OltConfig(
        name=item["name"], host=item["host"], port=item["snmp_port"], community=item["community"],
        vendor=item.get("vendor"), status_interval=item["status_interval_s"],
        optical_interval=item["optical_interval_s"], olt_id=item["id"], tenant_id=item["tenant_id"],
        sys_name=item.get("sys_name"),
    )


class ApiRegistry:
    def __init__(self, api_url: str, token: str, client: SnmpClient, sink: Sink, receiver: TrapReceiver | None = None,
                 interval: float = 30.0, http: httpx.AsyncClient | None = None):
        self.url = api_url.rstrip("/") + "/api/internal/collector/olts"
        self.token = token
        self.client = client
        self.sink = sink
        self.receiver = receiver
        self.interval = interval
        self.http = http or httpx.AsyncClient(timeout=10)
        self.workers: dict[str, OltWorker] = {}

    async def fetch(self) -> list[OltConfig]:
        resp = await self.http.get(self.url, headers={"X-Service-Token": self.token})
        resp.raise_for_status()
        return [config_from_api(item) for item in resp.json()]

    async def apply(self, configs: list[OltConfig]) -> None:
        wanted = {c.olt_id: c for c in configs}
        for olt_id in list(self.workers):
            w = self.workers[olt_id]
            new = wanted.get(olt_id)
            if new is None or _access_changed(w.cfg, new):
                await w.stop()
                del self.workers[olt_id]
                log.info("OLT %s %s", w.cfg.name, "removida" if new is None else "alterada, reiniciando")
            else:
                w.cfg = new          # nome/sysName podem mudar sem reiniciar a coleta
        for olt_id, cfg in wanted.items():
            if olt_id not in self.workers:
                w = OltWorker(cfg, self.client, self.sink)
                self.workers[olt_id] = w
                w.start()
                log.info("coletando %s (%s:%s)", cfg.name, cfg.host, cfg.port)
        if self.receiver:
            self.receiver.set_workers(list(self.workers.values()))

    async def sync_once(self) -> bool:
        try:
            await self.apply(await self.fetch())
            return True
        except (httpx.HTTPError, ValueError, KeyError) as e:
            # API fora do ar: mantém a coleta atual e tenta de novo depois
            log.warning("não consegui ler as OLTs da API (%s); mantendo %d OLT(s)", e, len(self.workers))
            return False

    async def run(self) -> None:
        while True:
            await self.sync_once()
            await asyncio.sleep(self.interval)

    async def close(self) -> None:
        for w in self.workers.values():
            await w.stop()
        await self.http.aclose()


def _access_changed(old: OltConfig, new: OltConfig) -> bool:
    keys = ("host", "port", "community", "status_interval", "optical_interval")
    return any(getattr(old, k) != getattr(new, k) for k in keys)
