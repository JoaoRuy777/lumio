"""Aplica as migrações SQL de db/migrations em ordem, uma única vez cada.

    DATABASE_URL=postgresql://lumio:...@localhost:5432/lumio python db/migrate.py

Roda como o dono do banco (usuário do POSTGRES_USER). Antes das migrações,
cria/atualiza os papéis usados pelos serviços:

- lumio_app     (API): sujeito a RLS
- lumio_system  (worker): BYPASSRLS, processa todos os tenants

As senhas vêm de LUMIO_APP_DB_PASSWORD e LUMIO_SYSTEM_DB_PASSWORD.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import asyncpg

MIGRATIONS = Path(__file__).parent / "migrations"
log = logging.getLogger("lumio_migrate")

ROLES = {
    "lumio_app": ("LUMIO_APP_DB_PASSWORD", "NOBYPASSRLS"),
    "lumio_system": ("LUMIO_SYSTEM_DB_PASSWORD", "BYPASSRLS"),
}


async def ensure_roles(conn: asyncpg.Connection) -> None:
    for role, (env, rls) in ROLES.items():
        password = os.environ.get(env)
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        if not exists:
            await conn.execute(f"CREATE ROLE {role} LOGIN {rls}")
        if password:
            # identificadores fixos acima; a senha vai como literal escapado
            literal = await conn.fetchval("SELECT quote_literal($1)", password)
            await conn.execute(f"ALTER ROLE {role} WITH LOGIN {rls} PASSWORD {literal}")
        elif not exists:
            log.warning("%s não definida: papel %s criado sem senha (não consegue logar)", env, role)


async def migrate(dsn: str, migrations_dir: Path = MIGRATIONS) -> list[str]:
    conn = await asyncpg.connect(dsn)
    try:
        await ensure_roles(conn)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
        applied = []
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", path.name)
            log.info("aplicada %s", path.name)
            applied.append(path.name)
        if not applied:
            log.info("banco já está atualizado")
        return applied
    finally:
        await conn.close()


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("defina DATABASE_URL")
    # o Postgres pode ainda estar subindo
    for attempt in range(30):
        try:
            await migrate(dsn)
            return
        except (OSError, asyncpg.CannotConnectNowError) as e:
            log.info("aguardando o Postgres (%s)", e)
            await asyncio.sleep(1)
    sys.exit("Postgres não respondeu")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
