"""Consome o Redis Stream do coletor com consumer group.

Entrega "pelo menos uma vez": a mensagem só recebe XACK depois que a
transação do Postgres foi confirmada. Se o worker cair no meio, ao voltar ele
reprocessa as pendentes (id "0") antes das novas (">"). Reprocessar é seguro
porque os alarmes são deduplicados.
"""

from __future__ import annotations

import asyncio
import json
import logging

import asyncpg
import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

from .processor import Processor

log = logging.getLogger("lumio_worker.consumer")

# Falhas de infraestrutura: não confirma a mensagem, espera e tenta de novo
TRANSIENT = (OSError, RedisConnectionError, asyncpg.InterfaceError, asyncpg.CannotConnectNowError,
             asyncpg.PostgresConnectionError)


class Consumer:
    def __init__(self, r: redis.Redis, processor: Processor, stream: str = "lumio:readings",
                 group: str = "worker", consumer: str = "worker-1", batch: int = 100, block_ms: int = 2000):
        self.redis = r
        self.processor = processor
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.batch = batch
        self.block_ms = block_ms
        self.dead_letter = f"{stream}:dead"
        self.processed = 0
        self.failed = 0

    async def ensure_group(self) -> None:
        try:
            # "0": na primeira vez, processa também o que já estava no stream
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def _process(self, msg_id: str, fields: dict) -> None:
        try:
            record = json.loads(fields["data"])
        except (KeyError, ValueError):
            log.warning("mensagem %s inválida, descartada", msg_id)
            await self._dead(msg_id, fields, "json inválido")
            return
        try:
            await self.processor.handle(record)
        except TRANSIENT:
            raise
        except Exception as e:
            # Erro de dado ou de regra: não adianta repetir. Vai para o dead letter.
            log.exception("falha processando %s (%s)", msg_id, record.get("type"))
            await self._dead(msg_id, fields, repr(e))
            return
        await self.redis.xack(self.stream, self.group, msg_id)
        self.processed += 1

    async def _dead(self, msg_id: str, fields: dict, error: str) -> None:
        self.failed += 1
        await self.redis.xadd(self.dead_letter, {**fields, "error": error, "id": msg_id}, maxlen=10_000)
        await self.redis.xack(self.stream, self.group, msg_id)

    async def read_once(self, start: str) -> int:
        """Lê e processa um lote. start="0" = pendentes; ">" = novas."""
        resp = await self.redis.xreadgroup(self.group, self.consumer, {self.stream: start},
                                           count=self.batch, block=self.block_ms)
        entries = resp[0][1] if resp else []
        for msg_id, fields in entries:
            await self._process(msg_id, fields)
        return len(entries)

    async def run(self) -> None:
        await self.ensure_group()
        start = "0"
        while True:
            try:
                n = await self.read_once(start)
                if start == "0" and n == 0:
                    start = ">"      # acabaram as pendentes
            except TRANSIENT as e:
                log.warning("infraestrutura indisponível (%s); tentando de novo em 2 s", e)
                start = "0"
                await asyncio.sleep(2)
