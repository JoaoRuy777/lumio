"""API HTTP do simulador: consultar o estado da rede e disparar cenários."""

from __future__ import annotations

import inspect
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .model import SCENARIOS, Network
from .snmp_agent import TrapSender


class ScenarioRequest(BaseModel):
    type: Literal[SCENARIOS]  # type: ignore[valid-type]
    olt: str | None = None
    pon: str | None = Field(None, examples=["0/1/0"])
    onu: int | None = None
    cause: str | None = None
    rate_db_per_min: float | None = None
    target_dbm: float | None = None
    cpu: float | None = None


class TickRequest(BaseModel):
    minutes: float = 1.0


def create_app(network: Network, traps: TrapSender) -> FastAPI:
    app = FastAPI(title="Lumio — simulador de OLTs", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ok", "olts": len(network.olts), "traps_sent": traps.sent}

    @app.get("/olts")
    def list_olts():
        out = []
        for o in network.olts.values():
            onus = [u for p in o.pons.values() for u in p.onus.values()]
            out.append({
                "name": o.name, "vendor": o.vendor, "model": o.model,
                "snmp": f"{o.host}:{o.port}", "community": o.community,
                "reachable": o.reachable, "cpu": o.cpu, "temperature": o.temperature,
                "pon_ports": len(o.pons),
                "onus_online": sum(u.online for u in onus), "onus_total": len(onus),
            })
        return out

    @app.get("/olts/{name}")
    def get_olt(name: str):
        try:
            o = network.olt(name)
        except LookupError as e:
            raise HTTPException(404, str(e))
        return {
            "name": o.name, "reachable": o.reachable, "cpu": o.cpu,
            "pons": {
                p.name: [
                    {k: v for k, v in asdict(u).items() if k in ("onu_id", "serial", "online", "down_cause", "rx", "tx")}
                    for u in p.onus.values()
                ]
                for p in o.pons.values()
            },
        }

    @app.post("/scenarios")
    async def run_scenario(req: ScenarioRequest):
        handler = getattr(network, req.type)
        accepted = inspect.signature(handler).parameters
        params = {k: v for k, v in req.model_dump(exclude={"type"}).items() if v is not None and k in accepted}
        try:
            events = network.run(req.type, **params)
        except (LookupError, TypeError) as e:
            raise HTTPException(400, str(e))
        await traps.send(events)
        return {"scenario": req.type, "traps": [asdict(e) for e in events]}

    @app.post("/tick")
    async def tick(req: TickRequest):
        """Avança o relógio na mão (útil nos testes para não esperar)."""
        events = network.tick(req.minutes)
        await traps.send(events)
        return {"traps": [asdict(e) for e in events]}

    return app
