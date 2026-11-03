"""Dependências do FastAPI: usuário logado e conexão já presa ao tenant dele."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated, AsyncIterator
from uuid import UUID

import asyncpg
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from .db import tenant_tx
from .security import Cipher, decode_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: UUID
    tenant_id: UUID
    role: str


def settings(request: Request) -> Settings:
    return request.app.state.settings


def pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


def cipher(request: Request) -> Cipher:
    return request.app.state.cipher


def current_user(
    cfg: Annotated[Settings, Depends(settings)],
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "faça login", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(cfg.jwt_secret, cred.credentials)
        return CurrentUser(UUID(claims["sub"]), UUID(claims["tid"]), claims.get("role", "operator"))
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão inválida ou expirada",
                            headers={"WWW-Authenticate": "Bearer"})


async def tenant_db(
    user: Annotated[CurrentUser, Depends(current_user)],
    db_pool: Annotated[asyncpg.Pool, Depends(pool)],
) -> AsyncIterator[asyncpg.Connection]:
    """Transação com app.tenant_id = tenant do token. O RLS faz o resto."""
    async with tenant_tx(db_pool, user.tenant_id) as conn:
        yield conn


def require_admin(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "só administradores podem alterar o cadastro")
    return user


def service_auth(
    cfg: Annotated[Settings, Depends(settings)],
    x_service_token: Annotated[str | None, Header()] = None,
) -> None:
    if not x_service_token or not hmac.compare_digest(x_service_token, cfg.service_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token de serviço inválido")


User = Annotated[CurrentUser, Depends(current_user)]
Admin = Annotated[CurrentUser, Depends(require_admin)]
# scope="function": a transação é confirmada antes de a resposta sair, então o
# cliente nunca recebe 200 de algo que depois falhou no COMMIT
TenantDb = Annotated[asyncpg.Connection, Depends(tenant_db, scope="function")]
