"""Sobe o simulador: agentes SNMP das OLTs, relógio e API HTTP.

    python -m lumio_sim --config config/rede-exemplo.yaml --trap-target 127.0.0.1:1162
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn
import yaml

from .api import create_app
from .model import Network
from .snmp_agent import TrapSender, start_agents

log = logging.getLogger("lumio_sim")


def parse_target(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    return host, int(port)


async def clock(network: Network, traps: TrapSender, tick_seconds: float, speed: float) -> None:
    while True:
        await asyncio.sleep(tick_seconds)
        await traps.send(network.tick(tick_seconds / 60 * speed))


async def main() -> None:
    ap = argparse.ArgumentParser(description="Simulador de OLTs da Lumio")
    ap.add_argument("--config", default="config/rede-exemplo.yaml")
    ap.add_argument("--api-host", default="0.0.0.0")
    ap.add_argument("--api-port", type=int, default=8080)
    ap.add_argument("--trap-target", action="append", default=[], type=parse_target,
                    help="host:porta que recebe as traps (pode repetir)")
    ap.add_argument("--tick-seconds", type=float, default=10.0)
    ap.add_argument("--speed", type=float, default=1.0, help="minutos simulados por minuto real")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with open(args.config, encoding="utf-8") as f:
        network = Network.from_config(yaml.safe_load(f))

    traps = TrapSender(network, args.trap_target)
    await start_agents(network)
    asyncio.create_task(clock(network, traps, args.tick_seconds, args.speed))
    log.info("traps para %s", args.trap_target or "ninguém")

    server = uvicorn.Server(uvicorn.Config(create_app(network, traps), host=args.api_host, port=args.api_port, log_level="warning"))
    log.info("API de cenários em http://%s:%s/docs", args.api_host, args.api_port)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
