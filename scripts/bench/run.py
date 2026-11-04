"""Teste de carga de um nível (roda dentro da rede do compose, pelo bench.sh).

    python scripts/bench/run.py --olts 50 --faults 40 --out scripts/bench/out/nivel-50.json

Passos:
1. cria um provedor e cadastra as N OLTs do simulador pela API (mede a descoberta);
2. espera todas entrarem em coleta;
3. janela de medição: provoca F quedas de ONU (uma por segundo, em ONUs
   diferentes) e mede, para cada uma, o tempo do pedido ao simulador até o
   alarme gravado no banco (relógio único: todos os contêineres usam o do host);
4. lê do Redis os registros de estado (tempo de cada coleta SNMP);
5. rajada: injeta R registros de estado (128 ONUs cada) direto na fila e mede
   quanto tempo o worker leva para zerar a fila (ONUs processadas por segundo).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import time
import uuid
from datetime import datetime, timezone

import asyncpg
import httpx
import redis.asyncio as redis

API = os.environ.get("BENCH_API", "http://api:8000/api")
SIM = os.environ.get("BENCH_SIM", "http://simulator:8080")
REDIS = os.environ.get("BENCH_REDIS", "redis://redis:6379/0")
DB = os.environ["LUMIO_BENCH_DB"]
STREAM, GROUP = "lumio:readings", "worker"
PONS = ["0/1/0", "0/1/1", "0/1/2", "0/1/3"]


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def summary(values: list[float]) -> dict:
    return {"n": len(values), "min": round(min(values), 1) if values else None,
            "p50": pct(values, 50), "p95": pct(values, 95), "p99": pct(values, 99),
            "max": round(max(values), 1) if values else None,
            "mean": round(statistics.fmean(values), 1) if values else None}


def now() -> float:
    return time.time()


async def setup(http: httpx.AsyncClient, db: asyncpg.Connection, n: int) -> tuple[dict, list[dict], list[float]]:
    email = f"bench-{n}-{uuid.uuid4().hex[:6]}@bench.lumio.com.br"
    r = await http.post(f"{API}/auth/signup", json={"company": f"Bench {n} OLTs", "name": "Bench",
                                                    "email": email, "password": "bench-senha-123"})
    r.raise_for_status()
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await http.get(f"{API}/auth/me", headers=headers)).json()
    await db.execute("UPDATE tenants SET olt_limit = $2 WHERE id = $1", uuid.UUID(me["tenant_id"]), n)

    sem = asyncio.Semaphore(5)
    discovery: list[float] = []

    async def register(i: int) -> dict:
        async with sem:
            t0 = time.perf_counter()
            r = await http.post(f"{API}/olts", headers=headers, timeout=60, json={
                "name": f"olt-{i + 1:03d}", "host": "simulator", "snmp_port": 16101 + i, "community": "public"})
            r.raise_for_status()
            discovery.append((time.perf_counter() - t0) * 1000)
            saved = r.json()
            assert saved["discovery"]["ok"], saved
            return saved["olt"]

    olts = await asyncio.gather(*(register(i) for i in range(n)))
    return headers, olts, discovery


async def wait_collecting(http: httpx.AsyncClient, headers: dict, timeout: float = 240) -> float:
    t0 = now()
    while now() - t0 < timeout:
        items = (await http.get(f"{API}/olts", headers=headers)).json()["items"]
        if all(o["collection_status"] == "ok" for o in items):
            return now() - t0
        await asyncio.sleep(2)
    raise TimeoutError("OLTs não entraram em coleta")


async def faults(http: httpx.AsyncClient, db: asyncpg.Connection, olts: list[dict], n_faults: int,
                 interval: float) -> dict:
    rng = random.Random(7)
    targets = rng.sample([(i, pon, onu) for i in range(len(olts)) for pon in PONS for onu in range(32)], n_faults)
    sent = []
    for i, pon, onu in targets:
        t0 = now()
        r = await http.post(f"{SIM}/scenarios", json={"type": "onu_down", "olt": f"olt-{i + 1:03d}", "pon": pon, "onu": onu})
        r.raise_for_status()
        sent.append((olts[i]["id"], pon, onu, t0))
        await asyncio.sleep(interval)
    await asyncio.sleep(5)

    total, pipeline, missing = [], [], 0
    for olt_id, pon, onu, t0 in sent:
        row = await db.fetchrow(
            "SELECT a.created_at, a.latency_ms FROM alarms a JOIN onus n ON n.id = a.onu_id "
            "JOIN pon_ports p ON p.id = n.pon_id WHERE a.olt_id = $1 AND p.name = $2 AND n.onu_index = $3 "
            "AND a.kind = 'onu_offline' AND a.created_at >= to_timestamp($4) ORDER BY a.created_at LIMIT 1",
            uuid.UUID(olt_id), pon, onu, t0)
        if row is None:
            missing += 1
            continue
        total.append((row["created_at"].timestamp() - t0) * 1000)
        pipeline.append(row["latency_ms"])
    # devolve as ONUs (não muda a carga do próximo nível)
    for i, pon, onu in targets:
        await http.post(f"{SIM}/scenarios", json={"type": "onu_up", "olt": f"olt-{i + 1:03d}", "pon": pon, "onu": onu})
    return {"faults": n_faults, "missing_alarms": missing,
            "latency_total_ms": summary(total), "latency_pipeline_ms": summary(pipeline), "samples_total_ms": total}


async def polling_stats(r: redis.Redis, olt_ids: set[str], since: float) -> dict:
    took, onus = [], []
    entries = await r.xrevrange(STREAM, count=20_000)
    for msg_id, fields in entries:
        if int(msg_id.split("-")[0]) / 1000 < since:
            break
        rec = json.loads(fields["data"])
        if rec.get("type") == "onu_status" and rec.get("olt_id") in olt_ids:
            took.append(rec["took_ms"])
            onus.append(len(rec["onus"]))
    rates = [n / (t / 1000) for n, t in zip(onus, took) if t > 0]
    return {"status_polls": len(took), "took_ms": summary(took), "onus_per_s_per_olt": summary(rates)}


async def burst(r: redis.Redis, olts: list[dict], records: int, kind: str = "onu_status") -> dict:
    """Rajada de registros na fila: mede o worker sozinho.

    onu_status: 128 ONUs online (o caso comum: nada mudou desde a última coleta).
    onu_optical: 128 leituras de potência normais (grava a série temporal).
    """
    rng = random.Random(1)
    if kind == "onu_status":
        template = [{"pon": pon, "onu": onu, "serial": None, "online": True} for pon in PONS for onu in range(32)]
    else:
        template = [{"pon": pon, "onu": onu, "rx_dbm": round(rng.uniform(-24, -18), 2), "tx_dbm": 2.2}
                    for pon in PONS for onu in range(32)]
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    payloads = []
    for k in range(records):
        o = olts[k % len(olts)]
        payloads.append(json.dumps({"type": kind, "olt": o["name"], "olt_id": o["id"],
                                    "tenant_id": None, "ts": ts, "took_ms": 0, "onus": template}))
    t0 = time.perf_counter()
    pipe = r.pipeline(transaction=False)
    for p in payloads:
        pipe.xadd(STREAM, {"data": p}, maxlen=100_000, approximate=True)
    await pipe.execute()
    while True:
        info = {g["name"]: g for g in await r.xinfo_groups(STREAM)}[GROUP]
        if info["lag"] == 0 and info["pending"] == 0:
            break
        await asyncio.sleep(0.05)
    secs = time.perf_counter() - t0
    return {"records": records, "onus_per_record": len(template), "seconds": round(secs, 2),
            "records_per_s": round(records / secs, 1), "onus_per_s": round(records * len(template) / secs)}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--olts", type=int, required=True)
    ap.add_argument("--faults", type=int, default=40)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--steady", type=float, default=70, help="segundos extras de observação (>= 1 ciclo de 60 s)")
    ap.add_argument("--burst", type=int, default=200)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    db = await asyncpg.connect(DB)
    r = redis.from_url(REDIS, decode_responses=True)
    async with httpx.AsyncClient(timeout=30) as http:
        await http.post(f"{SIM}/scenarios", json={"type": "reset"})
        print(f"[{args.olts} OLTs] cadastrando…", flush=True)
        headers, olts, discovery = await setup(http, db, args.olts)
        ready_s = await wait_collecting(http, headers)
        print(f"[{args.olts} OLTs] em coleta após {ready_s:.0f} s; medindo…", flush=True)

        window_start = now()
        lat = await faults(http, db, olts, args.faults, args.interval)
        await asyncio.sleep(args.steady)
        window_end = now()
        poll = await polling_stats(r, {o["id"] for o in olts}, window_start - 60)

        print(f"[{args.olts} OLTs] rajada de {args.burst} registros…", flush=True)
        b = await burst(r, olts, args.burst, "onu_status")
        bo = await burst(r, olts, args.burst, "onu_optical")

        result = {
            "olts": args.olts, "onus": args.olts * 128,
            "window": {"start": window_start, "end": window_end},
            "discovery_ms": summary(discovery), "ready_s": round(ready_s, 1),
            "alarms": lat, "polling": poll, "burst": b, "burst_optical": bo,
        }
        # sai do caminho do próximo nível: o coletor para de coletar estas OLTs
        for o in olts:
            await http.delete(f"{API}/olts/{o['id']}", headers=headers)
    await db.close()
    await r.aclose()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    t = lat["latency_total_ms"]
    print(f"[{args.olts} OLTs] latência p50 {t['p50']} ms, p95 {t['p95']} ms, p99 {t['p99']} ms; "
          f"rajada: estado {b["onus_per_s"]} ONUs/s, potência {bo["onus_per_s"]} ONUs/s", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
