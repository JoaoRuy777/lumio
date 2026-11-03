"""Fixtures do worker. Banco e Redis vêm de tests/db_fixtures.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.db_fixtures import REDIS_URL, needs_db, needs_redis  # noqa: F401  (usados pelos testes)


@pytest.fixture
async def processor(pool):
    from lumio_worker.processor import Processor

    p = Processor(pool, default_tenant="demo")
    await p.setup()
    return p


def rec(type_: str, olt: str = "olt-1", ts: datetime | None = None, **data) -> dict:
    """Registro no mesmo formato que o coletor publica (modo YAML, sem olt_id)."""
    ts = ts or datetime.now(timezone.utc)
    return {"type": type_, "olt": olt, "ts": ts.isoformat(timespec="milliseconds"), **data}
