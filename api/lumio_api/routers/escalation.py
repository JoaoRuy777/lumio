"""Regras de escalonamento: alarme sem ninguém assumir depois de X minutos avisa
um canal a mais (supervisor, gerente). Quem dispara é o notificador."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..audit import audit
from ..deps import Admin, TenantDb, User

router = APIRouter(prefix="/escalation-rules", tags=["escalonamento"])

Severity = Literal["critical", "major", "minor", "warning"]


class RuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=80, examples=["Supervisor do plantão"])
    min_severity: Severity = "critical"
    after_minutes: int = Field(ge=1, le=1440, examples=[15])
    channel_id: UUID
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    min_severity: Severity | None = None
    after_minutes: int | None = Field(default=None, ge=1, le=1440)
    channel_id: UUID | None = None
    enabled: bool | None = None


class RuleOut(BaseModel):
    id: UUID
    name: str
    min_severity: Severity
    after_minutes: int
    channel_id: UUID
    channel_name: str
    channel_type: str
    enabled: bool
    created_at: datetime
    escalations_30d: int                 # alarmes escalados por esta regra nos últimos 30 dias


SELECT = """
    SELECT r.*, c.name AS channel_name, c.type AS channel_type,
           (SELECT count(*) FROM alarm_escalations e
             WHERE e.rule_id = r.id AND e.created_at > now() - interval '30 days') AS escalations_30d
    FROM escalation_rules r JOIN notification_channels c ON c.id = r.channel_id
"""


async def fetch_rule(db: asyncpg.Connection, rule_id: UUID) -> RuleOut:
    row = await db.fetchrow(SELECT + " WHERE r.id = $1", rule_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "regra não encontrada")
    return RuleOut(**dict(row))


async def check_channel(db: asyncpg.Connection, channel_id: UUID) -> None:
    if not await db.fetchval("SELECT 1 FROM notification_channels WHERE id = $1", channel_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "canal de notificação não encontrado")


@router.get("", response_model=list[RuleOut], summary="Regras de escalonamento, da mais rápida para a mais lenta")
async def list_rules(user: User, db: TenantDb) -> list[RuleOut]:
    return [RuleOut(**dict(r)) for r in await db.fetch(SELECT + " ORDER BY r.after_minutes, r.name")]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED, summary="Cria uma regra (admin)")
async def create_rule(body: RuleIn, user: Admin, db: TenantDb, request: Request) -> RuleOut:
    await check_channel(db, body.channel_id)
    rule_id = await db.fetchval(
        "INSERT INTO escalation_rules (tenant_id, name, min_severity, after_minutes, channel_id, enabled) "
        "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
        user.tenant_id, body.name.strip(), body.min_severity, body.after_minutes, body.channel_id, body.enabled,
    )
    rule = await fetch_rule(db, rule_id)
    await audit(db, user.tenant_id, user.user_id, "escalation.create", request=request, target_type="escalation_rule",
                target_id=rule_id, label=rule.name,
                details={"min_severity": rule.min_severity, "after_minutes": rule.after_minutes, "channel": rule.channel_name})
    return rule


@router.patch("/{rule_id}", response_model=RuleOut, summary="Altera ou liga/desliga uma regra (admin)")
async def update_rule(rule_id: UUID, body: RuleUpdate, user: Admin, db: TenantDb, request: Request) -> RuleOut:
    changes = body.model_dump(exclude_none=True)
    if "channel_id" in changes:
        await check_channel(db, changes["channel_id"])
    if changes:
        cols = ", ".join(f"{k} = ${i}" for i, k in enumerate(changes, 2))
        if await db.execute(f"UPDATE escalation_rules SET {cols} WHERE id = $1", rule_id, *changes.values()) == "UPDATE 0":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "regra não encontrada")
    rule = await fetch_rule(db, rule_id)
    if changes:
        await audit(db, user.tenant_id, user.user_id, "escalation.update", request=request,
                    target_type="escalation_rule", target_id=rule_id, label=rule.name, details=changes)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga uma regra (admin)")
async def delete_rule(rule_id: UUID, user: Admin, db: TenantDb, request: Request) -> Response:
    name = await db.fetchval("DELETE FROM escalation_rules WHERE id = $1 RETURNING name", rule_id)
    if name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "regra não encontrada")
    await audit(db, user.tenant_id, user.user_id, "escalation.delete", request=request,
                target_type="escalation_rule", target_id=rule_id, label=name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
