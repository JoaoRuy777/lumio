from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata

import asyncpg
from fastapi import APIRouter, HTTPException, Request, status

from ..audit import audit, client_ip
from ..db import system_tx, tenant_tx
from ..deps import TenantDb, User, cipher, pool, settings
from ..schemas import (ForgotPasswordIn, LoginIn, MeOut, PasswordChangeIn, PlanUsage, ResetPasswordIn, SignupIn,
                       TokenOut)
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["autenticação"])


def slugify(name: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:40] or "provedor"
    return f"{slug}-{secrets.token_hex(3)}"     # sufixo: dois provedores com o mesmo nome


def _token(request: Request, user_id, tenant_id, role, session_version: int = 0) -> TokenOut:
    cfg = settings(request)
    return TokenOut(access_token=create_token(cfg.jwt_secret, user_id=user_id, tenant_id=tenant_id, role=role,
                                              ttl_minutes=cfg.token_ttl_minutes, session_version=session_version))


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
    async with tenant_tx(pool(request), row["tenant_id"]) as conn:
        await audit(conn, row["tenant_id"], row["user_id"], "auth.signup", request=request,
                    target_type="tenant", target_id=row["tenant_id"], label=body.company.strip())
    return _token(request, row["user_id"], row["tenant_id"], "admin")


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request) -> TokenOut:
    ip = client_ip(request)
    async with system_tx(pool(request)) as conn:
        wait = await conn.fetchval("SELECT lumio_login_wait($1, $2)", body.email, ip)
        row = await conn.fetchrow("SELECT * FROM lumio_login_lookup($1)", body.email)
        # travado: nem confere a senha (não dá para continuar adivinhando)
        ok = wait == 0 and verify_password(row["password_hash"] if row else None, body.password)
        if wait == 0:
            await conn.execute("SELECT lumio_login_record($1, $2, $3)", body.email, ip, ok)
    if row:                                   # e-mail desconhecido não tem provedor onde registrar
        action = "auth.login_blocked" if wait else "auth.login" if ok else "auth.login_failed"
        async with tenant_tx(pool(request), row["tenant_id"]) as conn:
            await audit(conn, row["tenant_id"], row["user_id"], action, request=request, target_type="user",
                        target_id=row["user_id"], label=body.email.lower())
    if wait:
        minutes = max(1, -(-wait // 60))
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"muitas tentativas erradas; tente de novo em {minutes} min",
                            headers={"Retry-After": str(wait)})
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "e-mail ou senha incorretos")
    return _token(request, row["user_id"], row["tenant_id"], row["role"], row["session_version"])


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


# ------------------------------------------------------------------ senha

@router.post("/password", response_model=TokenOut,
             summary="Troca a própria senha (pede a atual); as outras sessões abertas caem")
async def change_password(body: PasswordChangeIn, user: User, db: TenantDb, request: Request) -> TokenOut:
    current = await db.fetchval("SELECT password_hash FROM users WHERE id = $1", user.user_id)
    if not verify_password(current, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "senha atual incorreta")
    version = await db.fetchval(
        "UPDATE users SET password_hash = $2, session_version = session_version + 1 WHERE id = $1 "
        "RETURNING session_version", user.user_id, hash_password(body.new_password))
    await audit(db, user.tenant_id, user.user_id, "auth.password_changed", request=request,
                target_type="user", target_id=user.user_id)
    return _token(request, user.user_id, user.tenant_id, user.role, version)     # esta sessão continua


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/forgot", status_code=status.HTTP_202_ACCEPTED,
             summary="Esqueci minha senha: manda por e-mail um link que vale 1 hora")
async def forgot_password(body: ForgotPasswordIn, request: Request) -> dict:
    token = secrets.token_urlsafe(32)
    async with system_tx(pool(request)) as conn:
        await conn.fetchval("SELECT lumio_password_reset_request($1, $2, $3)",
                            body.email, _token_hash(token), cipher(request).encrypt(token))
    # mesma resposta exista ou não o e-mail: ninguém descobre quem tem conta
    return {"detail": "se o e-mail estiver cadastrado, enviamos um link para redefinir a senha"}


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT,
             summary="Define a nova senha com o link do e-mail (uso único)")
async def reset_password(body: ResetPasswordIn, request: Request) -> None:
    async with system_tx(pool(request)) as conn:
        ok = await conn.fetchval("SELECT lumio_password_reset_consume($1, $2)",
                                 _token_hash(body.token), hash_password(body.new_password))
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "link inválido ou vencido; peça um novo")
