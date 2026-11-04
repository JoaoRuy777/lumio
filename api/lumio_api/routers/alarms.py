"""Alarmes: lista com filtros e reconhecimento. Tudo sob RLS (tenant do token)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status

from ..deps import TenantDb, User
from ..schemas import AlarmOut, AlarmPage, Severity

log = logging.getLogger("lumio_api.alarms")
router = APIRouter(prefix="/alarms", tags=["alarmes"])

ALARM_SELECT = """
    SELECT a.*, o.name AS olt_name, p.name AS pon, n.onu_index, n.serial AS onu_serial,
           (SELECT count(*) FROM alarms c WHERE c.parent_id = a.id) AS children,
           u.name AS acknowledged_by_name
    FROM alarms a
    JOIN olts o ON o.id = a.olt_id
    LEFT JOIN pon_ports p ON p.id = a.pon_id
    LEFT JOIN onus n ON n.id = a.onu_id
    LEFT JOIN users u ON u.id = a.acknowledged_by
"""

# Mais grave primeiro
SEVERITY_ORDER = "CASE a.severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 WHEN 'minor' THEN 2 ELSE 3 END"

StatusFilter = Literal["open", "active", "acknowledged", "cleared", "all"]


def to_alarm(row: asyncpg.Record) -> AlarmOut:
    data = dict(row)
    data["details"] = json.loads(data["details"]) if isinstance(data["details"], str) else data["details"]
    data["acknowledged_by"] = data.pop("acknowledged_by_name")
    return AlarmOut(**{k: data[k] for k in AlarmOut.model_fields})


async def fetch_alarms(db: asyncpg.Connection, *, status_: StatusFilter = "open", severity: list[str] | None = None,
                       olt_id: UUID | None = None, onu_id: UUID | None = None, parent_id: UUID | None = None,
                       top_level: bool = True, since: datetime | None = None, until: datetime | None = None,
                       limit: int = 50, offset: int = 0) -> AlarmPage:
    where, args = [], []

    def add(cond: str, value) -> None:
        args.append(value)
        where.append(cond.replace("?", f"${len(args)}"))

    if status_ == "open":
        where.append("a.status <> 'cleared'")
    elif status_ != "all":
        add("a.status = ?", status_)
    if severity:
        add("a.severity = ANY(?)", severity)
    if olt_id:
        add("a.olt_id = ?", olt_id)
    if onu_id:
        add("a.onu_id = ?", onu_id)
    if parent_id:
        add("a.parent_id = ?", parent_id)
    elif top_level and not onu_id:
        where.append("a.parent_id IS NULL")       # ONUs de um rompimento aparecem dentro dele
    if since:
        add("a.created_at >= ?", since)
    if until:
        add("a.created_at < ?", until)

    cond = (" WHERE " + " AND ".join(where)) if where else ""
    total = await db.fetchval("SELECT count(*) FROM alarms a" + cond, *args)
    order = f"{SEVERITY_ORDER}, a.created_at DESC" if status_ in ("open", "active", "acknowledged") else "a.created_at DESC"
    rows = await db.fetch(f"{ALARM_SELECT}{cond} ORDER BY {order} LIMIT {int(limit)} OFFSET {int(offset)}", *args)
    return AlarmPage(items=[to_alarm(r) for r in rows], total=total)


async def publish_event(redis, tenant_id: UUID, event: dict) -> None:
    if redis is None:
        return
    try:
        await redis.publish(f"lumio:events:{tenant_id}", json.dumps(event))
    except Exception as e:          # tempo real é melhor-esforço; o dado já está no banco
        log.warning("não consegui avisar o painel (%s)", e)


@router.get("", response_model=AlarmPage,
            summary="Alarmes do provedor. Padrão: abertos, mais graves primeiro, sem as ONUs agrupadas")
async def list_alarms(
    user: User, db: TenantDb,
    status_: Annotated[StatusFilter, Query(alias="status")] = "open",
    severity: Annotated[list[Severity] | None, Query()] = None,
    olt_id: UUID | None = None,
    onu_id: UUID | None = None,
    parent_id: Annotated[UUID | None, Query(description="filhos de um rompimento de fibra")] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AlarmPage:
    return await fetch_alarms(db, status_=status_, severity=severity, olt_id=olt_id, onu_id=onu_id,
                              parent_id=parent_id, since=since, until=until, limit=limit, offset=offset)


@router.get("/{alarm_id}", response_model=AlarmOut)
async def get_alarm(alarm_id: UUID, user: User, db: TenantDb) -> AlarmOut:
    row = await db.fetchrow(ALARM_SELECT + " WHERE a.id = $1", alarm_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alarme não encontrado")
    return to_alarm(row)


@router.post("/{alarm_id}/ack", response_model=AlarmOut,
             summary="Reconhecer: alguém está cuidando. O alarme continua aberto até a falha passar")
async def acknowledge(alarm_id: UUID, user: User, db: TenantDb, request: Request,
                      background: BackgroundTasks) -> AlarmOut:
    row = await db.fetchrow("SELECT status FROM alarms WHERE id = $1", alarm_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alarme não encontrado")
    if row["status"] == "cleared":
        raise HTTPException(status.HTTP_409_CONFLICT, "alarme já encerrado")
    # reconhecer um rompimento reconhece também as ONUs agrupadas nele
    await db.execute(
        "UPDATE alarms SET status = 'acknowledged', acknowledged_at = now(), acknowledged_by = $2 "
        "WHERE (id = $1 OR parent_id = $1) AND status = 'active'", alarm_id, user.user_id)
    # roda depois da resposta, ou seja, depois do COMMIT
    background.add_task(publish_event, request.app.state.redis, user.tenant_id,
                        {"type": "alarm.acknowledged", "alarm_id": str(alarm_id)})
    return to_alarm(await db.fetchrow(ALARM_SELECT + " WHERE a.id = $1", alarm_id))
