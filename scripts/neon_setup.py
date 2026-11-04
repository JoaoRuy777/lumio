"""Prepara o banco da Lumio no Neon.

    neon deploy                         # cria o banco e grava .env.local
    docker compose run --rm --no-deps tests python scripts/neon_setup.py

1. Lê DATABASE_URL (pooled) e DATABASE_URL_UNPOOLED (direta) do .env.local.
2. Gera, se ainda não existir, .env.lumio.local com os segredos da Lumio (senhas
   dos papéis lumio_app/lumio_system, chave do JWT, chave Fernet, token do
   coletor). Arquivo separado porque o `neon deploy` reescreve o .env.local.
3. Aplica as migrações pela conexão DIRETA (o pooler não guarda estado de sessão).
4. Escreve no .env.lumio.local as URLs prontas de cada serviço:
   LUMIO_API_DATABASE_URL (pooled, papel lumio_app: API, Vercel) e
   LUMIO_SYSTEM_DATABASE_URL (direta, papel lumio_system: worker e notificador).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from migrate import migrate  # noqa: E402

NEON_ENV = Path(".env.local")
LUMIO_ENV = Path(".env.lumio.local")


def read_env(path: Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def with_user(url: str, user: str, password: str) -> str:
    p = urlsplit(url)
    host = p.hostname + (f":{p.port}" if p.port else "")
    return urlunsplit(p._replace(netloc=f"{user}:{quote(password, safe='')}@{host}"))


def ensure_secrets() -> dict[str, str]:
    env = read_env(LUMIO_ENV)
    wanted = {
        "LUMIO_APP_DB_PASSWORD": lambda: secrets.token_urlsafe(24),
        "LUMIO_SYSTEM_DB_PASSWORD": lambda: secrets.token_urlsafe(24),
        "LUMIO_JWT_SECRET": lambda: secrets.token_urlsafe(48),
        "LUMIO_SECRET_KEY": lambda: base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "LUMIO_SERVICE_TOKEN": lambda: secrets.token_urlsafe(32),
    }
    for k, make in wanted.items():
        env.setdefault(k, make())
    return env


def write(env: dict[str, str]) -> None:
    lines = ["# Segredos da Lumio para o Neon (gerado por scripts/neon_setup.py). NÃO commitar."]
    lines += [f'{k}="{v}"' for k, v in env.items()]
    LUMIO_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        LUMIO_ENV.chmod(0o600)
    except OSError:
        pass


async def main() -> None:
    neon = read_env(NEON_ENV)
    if "DATABASE_URL_UNPOOLED" not in neon:
        sys.exit("falta .env.local com DATABASE_URL_UNPOOLED: rode `neon deploy` antes")
    env = ensure_secrets()
    write(env)                       # grava antes: a senha dos papéis já vai ser usada
    os.environ["LUMIO_APP_DB_PASSWORD"] = env["LUMIO_APP_DB_PASSWORD"]
    os.environ["LUMIO_SYSTEM_DB_PASSWORD"] = env["LUMIO_SYSTEM_DB_PASSWORD"]
    applied = await migrate(neon["DATABASE_URL_UNPOOLED"])
    print("migrações aplicadas:", ", ".join(applied) or "nenhuma (já estava atualizado)")
    env["LUMIO_API_DATABASE_URL"] = with_user(neon["DATABASE_URL"], "lumio_app", env["LUMIO_APP_DB_PASSWORD"])
    env["LUMIO_SYSTEM_DATABASE_URL"] = with_user(neon["DATABASE_URL_UNPOOLED"], "lumio_system",
                                                 env["LUMIO_SYSTEM_DB_PASSWORD"])
    write(env)
    print(f"segredos e URLs em {LUMIO_ENV} (fora do git)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
