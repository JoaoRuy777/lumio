"""Fixtures dos testes do worker: Postgres e Redis de verdade.

Precisa de:
    LUMIO_TEST_DATABASE_URL  superusuário, ex. postgresql://lumio:lumio-dev@localhost:5432/postgres
    LUMIO_TEST_REDIS_URL     ex. redis://localhost:6379/15

Cada sessão de testes cria um banco descartável (lumio_test_xxxx), aplica as
migrações e apaga o banco no fim. Sem as variáveis, os testes são pulados
(no CI elas estão sempre definidas).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

from migrate import migrate

ADMIN_URL = os.environ.get("LUMIO_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("LUMIO_TEST_REDIS_URL")

needs_db = pytest.mark.skipif(not ADMIN_URL, reason="defina LUMIO_TEST_DATABASE_URL")
needs_redis = pytest.mark.skipif(not (ADMIN_URL and REDIS_URL), reason="defina LUMIO_TEST_DATABASE_URL e LUMIO_TEST_REDIS_URL")


def _with_db(url: str, db: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{db}"


@pytest.fixture(scope="session")
def test_db_url():
    if not ADMIN_URL:
        pytest.skip("defina LUMIO_TEST_DATABASE_URL")
    name = f"lumio_test_{uuid.uuid4().hex[:8]}"

    async def create():
        conn = await asyncpg.connect(ADMIN_URL)
        await conn.execute(f'CREATE DATABASE "{name}"')
        await conn.close()
        await migrate(_with_db(ADMIN_URL, name))

    async def drop():
        conn = await asyncpg.connect(ADMIN_URL)
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.close()

    asyncio.run(create())
    yield _with_db(ADMIN_URL, name)
    asyncio.run(drop())


@pytest.fixture
async def pool(test_db_url):
    pool = await asyncpg.create_pool(test_db_url, min_size=1, max_size=4)
    await pool.execute("TRUNCATE tenants CASCADE")
    yield pool
    await pool.close()


@pytest.fixture
async def processor(pool):
    from lumio_worker.processor import Processor

    p = Processor(pool, default_tenant="demo")
    await p.setup()
    return p


def rec(type_: str, olt: str = "olt-1", ts: datetime | None = None, **data) -> dict:
    """Registro no mesmo formato que o coletor publica."""
    ts = ts or datetime.now(timezone.utc)
    return {"type": type_, "olt": olt, "ts": ts.isoformat(timespec="milliseconds"), **data}
