"""Janelas de manutenção programada: durante a janela, os alarmes da OLT (ou de
uma PON) aparecem no painel marcados "em manutenção" e não disparam e-mail."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from ..deps import TenantDb, User

router = APIRouter(prefix="/maintenance", tags=["manutenção"])

MAX_DURATION = timedelta(days=7)
State = Literal["active", "scheduled", "finished", "cancelled"]


class MaintenanceIn(BaseModel):
    olt_id: UUID
    pon_id: UUID | None = None           # sem PON: a OLT inteira
    reason: str = Field(min_length=3, max_length=300, examples=["Troca da placa GPON 0/1"])
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def check_period(self) -> "MaintenanceIn":
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("informe data e hora com fuso (ex.: 2026-11-08T02:00:00-03:00)")
        if self.ends_at <= self.starts_at:
            raise ValueError("o fim precisa ser depois do início")
        if self.ends_at - self.starts_at > MAX_DURATION:
            raise ValueError("a janela pode durar no máximo 7 dias")
        if self.ends_at <= datetime.now(timezone.utc):
            raise ValueError("o fim da janela já passou")
        return self


class MaintenanceOut(BaseModel):
    id: UUID
    olt_id: UUID
    olt_name: str
    pon_id: UUID | None
    pon: str | None
    reason: str
    starts_at: datetime
    ends_at: datetime
    created_by: str | None
    created_at: datetime
    cancelled_at: datetime | None
    state: State
    alarms_silenced: int                 # alarmes abertos durante a janela (sem aviso)


SELECT = """
    SELECT m.*, o.name AS olt_name, p.name AS pon, u.name AS created_by_name,
           CASE WHEN m.cancelled_at IS NOT NULL THEN 'cancelled'
                WHEN now() < m.starts_at THEN 'scheduled'
                WHEN now() < m.ends_at THEN 'active'
                ELSE 'finished' END AS state,
           (SELECT count(*) FROM alarms a WHERE a.maintenance_id = m.id AND a.parent_id IS NULL) AS alarms_silenced
    FROM maintenance_windows m
    JOIN olts o ON o.id = m.olt_id
    LEFT JOIN pon_ports p ON p.id = m.pon_id
    LEFT JOIN users u ON u.id = m.created_by
"""


def to_out(row) -> MaintenanceOut:
    data = dict(row)
    data["created_by"] = data.pop("created_by_name")
    return MaintenanceOut(**data)


async def fetch_one(db, window_id: UUID) -> MaintenanceOut:
    row = await db.fetchrow(SELECT + " WHERE m.id = $1", window_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "janela de manutenção não encontrada")
    return to_out(row)


@router.get("", response_model=list[MaintenanceOut], summary="Janelas em andamento, agendadas e as recentes")
async def list_windows(user: User, db: TenantDb, current: bool = False) -> list[MaintenanceOut]:
    """`current=true`: só as em andamento (faixa de aviso do painel). Sem filtro: em andamento e
    agendadas primeiro, depois as encerradas/canceladas dos últimos 30 dias."""
    if current:
        where = "WHERE m.cancelled_at IS NULL AND m.starts_at <= now() AND m.ends_at > now()"
    else:
        where = "WHERE m.ends_at > now() - interval '30 days'"
    rows = await db.fetch(
        SELECT + where + " ORDER BY (m.cancelled_at IS NULL AND m.ends_at > now()) DESC, m.starts_at DESC LIMIT 200")
    return [to_out(r) for r in rows]


@router.post("", response_model=MaintenanceOut, status_code=status.HTTP_201_CREATED,
             summary="Agenda uma janela de manutenção (OLT inteira ou uma PON)")
async def create_window(body: MaintenanceIn, user: User, db: TenantDb) -> MaintenanceOut:
    if not await db.fetchval("SELECT 1 FROM olts WHERE id = $1", body.olt_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OLT não encontrada")
    if body.pon_id and not await db.fetchval("SELECT 1 FROM pon_ports WHERE id = $1 AND olt_id = $2",
                                             body.pon_id, body.olt_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "a PON não é desta OLT")
    window_id = await db.fetchval(
        "INSERT INTO maintenance_windows (tenant_id, olt_id, pon_id, reason, starts_at, ends_at, created_by) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
        user.tenant_id, body.olt_id, body.pon_id, body.reason.strip(), body.starts_at, body.ends_at, user.user_id,
    )
    return await fetch_one(db, window_id)


@router.post("/{window_id}/end", response_model=MaintenanceOut,
             summary="Encerra agora (em andamento) ou cancela (agendada)")
async def end_window(window_id: UUID, user: User, db: TenantDb) -> MaintenanceOut:
    w = await fetch_one(db, window_id)
    if w.state == "scheduled":
        await db.execute("UPDATE maintenance_windows SET cancelled_at = now() WHERE id = $1", window_id)
    elif w.state == "active":
        await db.execute("UPDATE maintenance_windows SET ends_at = now() WHERE id = $1", window_id)
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "a janela já terminou")
    return await fetch_one(db, window_id)
