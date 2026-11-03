"""Para onde o coletor manda o que leu.

Sprint 1: stdout (JSON por linha). Sprint 2: Redis Stream, que o worker
consome e grava no TimescaleDB.
"""

from __future__ import annotations

import json
import sys
from typing import Protocol


class Sink(Protocol):
    async def publish(self, record: dict) -> None: ...


class StdoutSink:
    async def publish(self, record: dict) -> None:
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
        sys.stdout.flush()


class MemorySink:
    """Guarda tudo numa lista (usado nos testes)."""

    def __init__(self):
        self.records: list[dict] = []

    async def publish(self, record: dict) -> None:
        self.records.append(record)

    def of(self, type_: str, **match) -> list[dict]:
        return [r for r in self.records if r["type"] == type_ and all(r.get(k) == v for k, v in match.items())]


class RedisStreamSink:
    def __init__(self, url: str, stream: str = "lumio:readings", maxlen: int = 100_000):
        import redis.asyncio as redis  # dependência opcional até a sprint 2

        self.redis = redis.from_url(url)
        self.stream = stream
        self.maxlen = maxlen

    async def publish(self, record: dict) -> None:
        await self.redis.xadd(self.stream, {"data": json.dumps(record)}, maxlen=self.maxlen, approximate=True)
