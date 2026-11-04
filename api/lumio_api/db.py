"""Acesso ao banco: toda consulta de dados do cliente roda numa transação com
app.tenant_id definido, e o RLS do Postgres filtra o resto.

Mesmo que uma consulta esqueça o WHERE tenant_id, o banco não devolve linhas
de outro tenant: o isolamento não depende de a API acertar todos os filtros.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg


async def create_pool(dsn: str, role: str | None = None) -> asyncpg.Pool:
    async def setup(conn: asyncpg.Connection) -> None:
        # Só nos testes: o pool conecta como superusuário e assume o papel da API
        if role:
            await conn.execute(f'SET ROLE "{role}"')

    return await asyncpg.create_pool(dsn, min_size=1, max_size=10, setup=setup if role else None,
                                     **pool_options(dsn))


def pool_options(dsn: str) -> dict:
    """Pooler em modo transação (PgBouncer, ex.: host "-pooler" do Neon): cada
    consulta pode cair numa conexão diferente, então o cache de prepared
    statements do asyncpg fica desligado. O app.tenant_id já é por transação
    (set_config(..., true)), o que o pooler preserva."""
    host = urlsplit(dsn).hostname or ""
    return {"statement_cache_size": 0} if "-pooler" in host else {}


@asynccontextmanager
async def tenant_tx(pool: asyncpg.Pool, tenant_id: UUID) -> AsyncIterator[asyncpg.Connection]:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
        yield conn


@asynccontextmanager
async def system_tx(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    """Sem tenant: só enxerga o que as funções SECURITY DEFINER liberam."""
    async with pool.acquire() as conn, conn.transaction():
        yield conn
