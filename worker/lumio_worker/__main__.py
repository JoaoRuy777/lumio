"""Worker de alarmes da Lumio.

    REDIS_URL=redis://localhost:6379/0 \
    DATABASE_URL=postgresql://lumio_system:...@localhost:5432/lumio \
    python -m lumio_worker
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket

import asyncpg
import redis.asyncio as redis

from .consumer import Consumer
from .processor import Processor

log = logging.getLogger("lumio_worker")

RETENTION_DAYS = int(os.environ.get("LUMIO_RETENTION_DAYS", "90"))


async def connect_pool(dsn: str) -> asyncpg.Pool:
    for _ in range(30):
        try:
            return await asyncpg.create_pool(dsn, min_size=1, max_size=4)
        except (OSError, asyncpg.CannotConnectNowError, asyncpg.InvalidPasswordError) as e:
            log.info("aguardando o Postgres (%s)", e)
            await asyncio.sleep(1)
    raise SystemExit("Postgres não respondeu")


async def retention(pool: asyncpg.Pool) -> None:
    """Apaga leituras antigas uma vez por hora (alarmes ficam para os relatórios)."""
    while True:
        async with pool.acquire() as conn:
            for table in ("optical_readings", "olt_health_readings"):
                result = await conn.execute(
                    f"DELETE FROM {table} WHERE ts < now() - make_interval(days => $1)", RETENTION_DAYS)
                if result != "DELETE 0":
                    log.info("retenção: %s em %s", result, table)
        await asyncio.sleep(3600)


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    pool = await connect_pool(dsn)
    r = redis.from_url(redis_url, decode_responses=True)
    processor = Processor(pool, default_tenant=os.environ.get("LUMIO_DEFAULT_TENANT", "demo"), redis=r)
    # setup() (tenant "demo") só roda se aparecer registro sem olt_id (modo YAML)
    consumer = Consumer(
        r, processor,
        stream=os.environ.get("LUMIO_STREAM", "lumio:readings"),
        group=os.environ.get("LUMIO_GROUP", "worker"),
        consumer=os.environ.get("LUMIO_CONSUMER", socket.gethostname()),
    )
    log.info("consumindo %s (grupo %s)", consumer.stream, consumer.group)
    asyncio.create_task(retention(pool))
    await consumer.run()


async def notify_main() -> None:
    """python -m lumio_worker notify: envia as notificações da fila."""
    from .notify import Notifier, SmtpConfig

    pool = await connect_pool(os.environ["DATABASE_URL"])
    smtp = SmtpConfig(
        host=os.environ.get("SMTP_HOST") or None,
        port=int(os.environ.get("SMTP_PORT", "587")),
        username=os.environ.get("SMTP_USER") or None,
        password=os.environ.get("SMTP_PASSWORD") or None,
        sender=os.environ.get("SMTP_FROM", "Lumio <alertas@lumio.local>"),
        security=os.environ.get("SMTP_SECURITY", "starttls"),
    )
    if not smtp.configured:
        log.warning("SMTP_HOST não definido: canais de e-mail vão falhar até configurar")
    notifier = Notifier(
        pool, os.environ["LUMIO_SECRET_KEY"], smtp,
        public_url=os.environ.get("LUMIO_PUBLIC_URL", ""),
        allow_private=os.environ.get("LUMIO_WEBHOOK_ALLOW_PRIVATE", "").lower() in ("1", "true", "yes"),
    )
    log.info("notificador no ar (SMTP %s)", smtp.host or "não configurado")
    await notifier.run()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(notify_main() if sys.argv[1:] == ["notify"] else main())
