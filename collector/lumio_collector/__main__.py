"""Coletor da Lumio.

    python -m lumio_collector run --config config/coletor-exemplo.yaml
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
    p = sub.add_parser("probe", help="testa a conexão com uma OLT (o mesmo do botão Testar conexão)")
    p.add_argument("address", help="host[:porta]")
    p.add_argument("--community", default="public")
    args = ap.parse_args()

    # Logs vão para stderr; stdout fica só com os registros JSON
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "run":
        asyncio.run(run(args.config))
    else:
        raise SystemExit(asyncio.run(run_probe(args.address, args.community)))


if __name__ == "__main__":
    main()
