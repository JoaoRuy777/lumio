from __future__ import annotations

import re
import secrets
import unicodedata

import asyncpg
from fastapi import APIRouter, HTTPException, Request, status

from ..db import system_tx
from ..deps import TenantDb, User, pool, settings
from ..schemas import LoginIn, MeOut, PlanUsage, SignupIn, TokenOut
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["autenticação"])


def slugify(name: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:40] or "provedor"
    return f"{slug}-{secrets.token_hex(3)}"     # sufixo: dois provedores com o mesmo nome


def _token(request: Request, user_id, tenant_id, role) -> TokenOut:
    cfg = settings(request)
    return TokenOut(access_token=create_token(cfg.jwt_secret, user_id=user_id, tenant_id=tenant_id, role=role,
                                              ttl_minutes=cfg.token_ttl_minutes))


@router.post("/signup", response_model=TokenOut, status_code=status.HTTP_201_CREATED,
             summary="Cria o provedor (tenant) e o primeiro usuário, administrador")
async def signup(body: SignupIn, request: Request) -> TokenOut:
    async with system_tx(pool(request)) as conn:
        try:
            row = await conn.fetchrow("SELECT * FROM lumio_signup($1, $2, $3, $4, $5)",
                                      body.company.strip(), slugify(body.company), body.email,
                                      body.name.strip(), hash_password(body.password))
        except asyncpg.UniqueViolationError:
            raise HTTPException(status.HTTP_409_CONFLICT, "e-mail já cadastrado")
    return _token(request, row["user_id"], row["tenant_id"], "admin")


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request) -> TokenOut:
    async with system_tx(pool(request)) as conn:
        row = await conn.fetchrow("SELECT * FROM lumio_login_lookup($1)", body.email)
    if not verify_password(row["password_hash"] if row else None, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "e-mail ou senha incorretos")
    return _token(request, row["user_id"], row["tenant_id"], row["role"])


@router.get("/me", response_model=MeOut)
async def me(user: User, db: TenantDb) -> MeOut:
    row = await db.fetchrow(
        "SELECT u.email, u.name, u.role, t.name AS tenant_name, t.olt_limit, "
        "       (SELECT count(*) FROM olts) AS olts_used "
        "FROM users u JOIN tenants t ON t.id = u.tenant_id WHERE u.id = $1", user.user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuário não existe mais")
    return MeOut(user_id=user.user_id, email=row["email"], name=row["name"], role=row["role"],
                 tenant_id=user.tenant_id, tenant_name=row["tenant_name"],
                 olts=PlanUsage(used=row["olts_used"], limit=row["olt_limit"]))
