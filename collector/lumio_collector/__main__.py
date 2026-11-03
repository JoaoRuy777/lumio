"""Coletor da Lumio.

    python -m lumio_collector run --config config/coletor-exemplo.yaml   # OLTs do YAML
    LUMIO_API_URL=http://localhost:8000 LUMIO_SERVICE_TOKEN=... python -m lumio_collector run-api
    python -m lumio_collector probe 127.0.0.1:16101 --community public
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

import yaml

from .poller import OltConfig, OltWorker, probe
from .registry import ApiRegistry
from .sink import RedisStreamSink, StdoutSink
from .snmp import SnmpClient, SnmpError, Target
from .traps import start_trap_receiver


async def run(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    redis_url = os.environ.get("REDIS_URL") or cfg.get("redis_url")
    sink = RedisStreamSink(redis_url) if redis_url else StdoutSink()
    defaults = cfg.get("defaults", {})
    client = SnmpClient()
    workers = [OltWorker(OltConfig(**{**defaults, **o}), client, sink) for o in cfg["olts"]]
    host, _, port = cfg.get("trap_listen", "0.0.0.0:1162").rpartition(":")
    await start_trap_receiver(workers, host, int(port))
    for w in workers:
        w.start()
    logging.getLogger("lumio_collector").info("coletando %d OLT(s)", len(workers))
    await asyncio.Event().wait()


async def run_api(api_url: str, token: str, trap_listen: str, interval: float) -> None:
    """OLTs vindas do cadastro na API, atualizadas a cada `interval` segundos."""
    redis_url = os.environ.get("REDIS_URL")
    sink = RedisStreamSink(redis_url) if redis_url else StdoutSink()
    client = SnmpClient()
    host, _, port = trap_listen.rpartition(":")
    receiver = await start_trap_receiver([], host, int(port))
    registry = ApiRegistry(api_url, token, client, sink, receiver, interval=interval)
    logging.getLogger("lumio_collector").info("lendo OLTs de %s a cada %.0f s", api_url, interval)
    await registry.run()


async def run_probe(address: str, community: str) -> int:
    host, _, port = address.rpartition(":") if ":" in address else (address, "", "161")
    client = SnmpClient()
    try:
        result = await probe(client, Target(host, int(port), community))
    except SnmpError as e:
        result = {"ok": False, "error": f"sem resposta SNMP: {e}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Coletor SNMP da Lumio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="coleta contínua das OLTs do arquivo de configuração")
    r.add_argument("--config", default="config/coletor-exemplo.yaml")
    a = sub.add_parser("run-api", help="coleta contínua das OLTs cadastradas na API")
    a.add_argument("--api-url", default=os.environ.get("LUMIO_API_URL", "http://localhost:8000"))
    a.add_argument("--trap-listen", default="0.0.0.0:1162")
    a.add_argument("--interval", type=float, default=30.0, help="segundos entre leituras do cadastro")
    p = sub.add_parser("probe", help="testa a conexão com uma OLT (o mesmo do botão Testar conexão)")
    p.add_argument("address", help="host[:porta]")
    p.add_argument("--community", default="public")
    args = ap.parse_args()

    # Logs vão para stderr; stdout fica só com os registros JSON
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "run":
        asyncio.run(run(args.config))
    elif args.cmd == "run-api":
        token = os.environ.get("LUMIO_SERVICE_TOKEN")
        if not token:
            raise SystemExit("defina LUMIO_SERVICE_TOKEN")
        asyncio.run(run_api(args.api_url, token, args.trap_listen, args.interval))
    else:
        raise SystemExit(asyncio.run(run_probe(args.address, args.community)))


if __name__ == "__main__":
    main()
