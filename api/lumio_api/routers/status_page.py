"""Página pública de status: o cliente final vê se há interrupção no bairro dele.

- GET  /public/status/{slug}  sem login; só o que a função lumio_public_status libera
- GET  /status-page           admin: se está ligada e qual o endereço
- PUT  /status-page           admin: liga/desliga e troca o endereço
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Literal

import asyncpg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..audit import audit
from ..db import system_tx
from ..deps import Admin, TenantDb, pool

public_router = APIRouter(prefix="/public", tags=["página pública"])
router = APIRouter(prefix="/status-page", tags=["página pública"])

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,46}[a-z0-9]$")
# CDN e navegador guardam por 30 s: a página aguenta muito acesso sem pesar no banco
PUBLIC_CACHE = "public, max-age=30, s-maxage=30"


class StatusIncident(BaseModel):
    kind: Literal["pon_fiber_cut", "olt_unreachable"]
    since: datetime
    until: datetime | None = None
    districts: list[str]


class StatusMaintenance(BaseModel):
    starts_at: datetime
    ends_at: datetime
    in_progress: bool
    districts: list[str]


class PublicStatus(BaseModel):
    name: str
    updated_at: datetime
    incidents: list[StatusIncident]
    maintenance: list[StatusMaintenance]
    history: list[StatusIncident]


class StatusPageSettings(BaseModel):
    enabled: bool
    slug: str


class StatusPageUpdate(BaseModel):
    enabled: bool
    slug: str = Field(min_length=1, max_length=48)


@public_router.get("/status/{slug}", response_model=PublicStatus, summary="Status público da rede do provedor")
async def public_status(slug: str, request: Request, response: Response) -> PublicStatus:
    if not SLUG_RE.match(slug.lower()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "página não encontrada")
    async with system_tx(pool(request)) as conn:
        raw = await conn.fetchval("SELECT lumio_public_status($1)", slug)
    if raw is None:
        # endereço inexistente e página desligada respondem igual
        raise HTTPException(status.HTTP_404_NOT_FOUND, "página não encontrada")
    response.headers["cache-control"] = PUBLIC_CACHE
    return PublicStatus(**(json.loads(raw) if isinstance(raw, str) else raw))


@router.get("", response_model=StatusPageSettings, summary="Configuração da página pública")
async def get_settings(user: Admin, db: TenantDb) -> StatusPageSettings:
    row = await db.fetchrow("SELECT status_page_enabled, slug FROM tenants")
    return StatusPageSettings(enabled=row["status_page_enabled"], slug=row["slug"])


@router.put("", response_model=StatusPageSettings, summary="Liga/desliga a página pública e define o endereço")
async def update_settings(body: StatusPageUpdate, user: Admin, db: TenantDb, request: Request) -> StatusPageSettings:
    slug = body.slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "endereço inválido: use letras minúsculas, números e hífen (2 a 48 caracteres)")
    before = await db.fetchrow("SELECT status_page_enabled, slug FROM tenants")
    try:
        async with db.transaction():
            await db.execute("UPDATE tenants SET status_page_enabled = $1, slug = $2 WHERE id = $3",
                             body.enabled, slug, user.tenant_id)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status.HTTP_409_CONFLICT, "esse endereço já está em uso; escolha outro")
    await audit(db, user.tenant_id, user.user_id, "status_page.update", request=request, target_type="status_page",
                label=f"/status/{slug}",
                details={"enabled": body.enabled, "slug": slug, "before": {"enabled": before["status_page_enabled"],
                                                                         "slug": before["slug"]}})
    return StatusPageSettings(enabled=body.enabled, slug=slug)
