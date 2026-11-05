"""Alarmes e o atendimento deles (chamados). Tudo sob RLS (tenant do token).

Atendimento: o operador assume (ou transfere), anota o que fez e encerra com a
causa. Cada passo vira um evento na linha do tempo (alarm_events).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status

from ..deps import TenantDb, User
from ..schemas import AlarmOut, AlarmPage, AssignIn, CloseIn, NoteIn, Severity, TimelineItem

log = logging.getLogger("lumio_api.alarms")
router = APIRouter(prefix="/alarms", tags=["alarmes"])

ALARM_SELECT = """
    SELECT a.*, o.name AS olt_name, p.name AS pon, n.onu_index, n.serial AS onu_serial,
           (SELECT count(*) FROM alarms c WHERE c.parent_id = a.id) AS children,
           u.name AS acknowledged_by_name, ua.name AS assigned_to_name, uc.name AS work_closed_by_name,
           cu.name AS customer_name, mw.reason AS maintenance_reason,
           (SELECT count(*) FROM alarms c JOIN onus cn ON cn.id = c.onu_id
              JOIN customers cc ON cc.tenant_id = cn.tenant_id AND cc.onu_serial = cn.serial
             WHERE c.parent_id = a.id) AS affected_customers
    FROM alarms a
    JOIN olts o ON o.id = a.olt_id
    LEFT JOIN pon_ports p ON p.id = a.pon_id
    LEFT JOIN onus n ON n.id = a.onu_id
    LEFT JOIN users u ON u.id = a.acknowledged_by
    LEFT JOIN users ua ON ua.id = a.assigned_to
    LEFT JOIN users uc ON uc.id = a.work_closed_by
    LEFT JOIN customers cu ON cu.tenant_id = a.tenant_id AND cu.onu_serial = n.serial
    LEFT JOIN maintenance_windows mw ON mw.id = a.maintenance_id
"""

# Mais grave primeiro
SEVERITY_ORDER = "CASE a.severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 WHEN 'minor' THEN 2 ELSE 3 END"

StatusFilter = Literal["open", "active", "acknowledged", "cleared", "all"]


def to_alarm(row: asyncpg.Record) -> AlarmOut:
    data = dict(row)
    data["details"] = json.loads(data["details"]) if isinstance(data["details"], str) else data["details"]
    data["acknowledged_by"] = data.pop("acknowledged_by_name")
    data["assigned_to_id"] = data["assigned_to"]
    data["assigned_to"] = data.pop("assigned_to_name")
    data["work_closed_by"] = data.pop("work_closed_by_name")
    return AlarmOut(**{k: data[k] for k in AlarmOut.model_fields})


async def fetch_alarms(db: asyncpg.Connection, *, status_: StatusFilter = "open", severity: list[str] | None = None,
                       olt_id: UUID | None = None, onu_id: UUID | None = None, parent_id: UUID | None = None,
                       top_level: bool = True, since: datetime | None = None, until: datetime | None = None,
                       assigned_to: UUID | None = None, work_open: bool | None = None,
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
    if assigned_to:
        add("a.assigned_to = ?", assigned_to)
    if work_open is True:
        where.append("a.work_closed_at IS NULL")
    elif work_open is False:
        where.append("a.work_closed_at IS NOT NULL")
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
    mine: Annotated[bool, Query(description="só os chamados comigo ainda não encerrados (ignora status)")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AlarmPage:
    if mine:
        return await fetch_alarms(db, status_="all", severity=severity, assigned_to=user.user_id, work_open=True,
                                  since=since, until=until, limit=limit, offset=offset)
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


# ------------------------------------------------------------------ atendimento

async def _chamado(db, alarm_id: UUID) -> asyncpg.Record:
    row = await db.fetchrow("SELECT id, parent_id, status, assigned_to, work_closed_at FROM alarms "
                            "WHERE id = $1 FOR UPDATE", alarm_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alarme não encontrado")
    if row["parent_id"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "esta ONU faz parte de um rompimento: atenda o chamado do rompimento")
    return row


async def _event(db, user, alarm_id: UUID, kind: str, *, target: UUID | None = None, body: str | None = None) -> None:
    await db.execute("INSERT INTO alarm_events (tenant_id, alarm_id, kind, actor_id, target_id, body) "
                     "VALUES ($1, $2, $3, $4, $5, $6)", user.tenant_id, alarm_id, kind, user.user_id, target, body)


async def _changed(db, request: Request, background: BackgroundTasks, user, alarm_id: UUID) -> AlarmOut:
    background.add_task(publish_event, request.app.state.redis, user.tenant_id,
                        {"type": "alarm.updated", "alarm_id": str(alarm_id)})
    return to_alarm(await db.fetchrow(ALARM_SELECT + " WHERE a.id = $1", alarm_id))


@router.post("/{alarm_id}/assign", response_model=AlarmOut,
             summary="Assumir o chamado (sem user_id) ou transferir para outro usuário do provedor")
async def assign(alarm_id: UUID, body: AssignIn, user: User, db: TenantDb, request: Request,
                 background: BackgroundTasks) -> AlarmOut:
    row = await _chamado(db, alarm_id)
    if row["work_closed_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "chamado encerrado: reabra para continuar o atendimento")
    target = body.user_id or user.user_id
    if not await db.fetchval("SELECT EXISTS (SELECT 1 FROM users WHERE id = $1)", target):   # RLS: só do provedor
        raise HTTPException(status.HTTP_404_NOT_FOUND, "usuário não encontrado")
    if row["assigned_to"] == target:
        return to_alarm(await db.fetchrow(ALARM_SELECT + " WHERE a.id = $1", alarm_id))
    await db.execute(
        "UPDATE alarms SET assigned_to = $2, assigned_at = now(), "
        "first_assigned_at = coalesce(first_assigned_at, now()) WHERE id = $1", alarm_id, target)
    # assumir também reconhece o alarme (e as ONUs agrupadas nele)
    await db.execute(
        "UPDATE alarms SET status = 'acknowledged', acknowledged_at = now(), acknowledged_by = $2 "
        "WHERE (id = $1 OR parent_id = $1) AND status = 'active'", alarm_id, user.user_id)
    await _event(db, user, alarm_id, "assigned", target=target)
    return await _changed(db, request, background, user, alarm_id)


@router.post("/{alarm_id}/notes", response_model=AlarmOut, status_code=status.HTTP_201_CREATED,
             summary="Anotar o que foi feito no chamado")
async def add_note(alarm_id: UUID, body: NoteIn, user: User, db: TenantDb, request: Request,
                   background: BackgroundTasks) -> AlarmOut:
    await _chamado(db, alarm_id)
    await _event(db, user, alarm_id, "note", body=body.body.strip())
    return await _changed(db, request, background, user, alarm_id)


@router.post("/{alarm_id}/close", response_model=AlarmOut,
             summary="Encerrar o atendimento com a causa e o que foi feito")
async def close(alarm_id: UUID, body: CloseIn, user: User, db: TenantDb, request: Request,
                background: BackgroundTasks) -> AlarmOut:
    row = await _chamado(db, alarm_id)
    if row["work_closed_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "chamado já encerrado")
    if row["assigned_to"] is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "assuma o chamado antes de encerrar")
    await db.execute(
        "UPDATE alarms SET work_closed_at = now(), work_closed_by = $2, resolution_cause = $3, "
        "resolution_notes = $4 WHERE id = $1", alarm_id, user.user_id, body.cause, body.notes.strip())
    await _event(db, user, alarm_id, "closed", body=body.notes.strip())
    return await _changed(db, request, background, user, alarm_id)


@router.post("/{alarm_id}/reopen", response_model=AlarmOut, summary="Reabrir um atendimento encerrado")
async def reopen(alarm_id: UUID, user: User, db: TenantDb, request: Request,
                 background: BackgroundTasks) -> AlarmOut:
    row = await _chamado(db, alarm_id)
    if row["work_closed_at"] is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "o chamado não está encerrado")
    await db.execute("UPDATE alarms SET work_closed_at = NULL, work_closed_by = NULL, resolution_cause = NULL, "
                     "resolution_notes = NULL WHERE id = $1", alarm_id)
    await _event(db, user, alarm_id, "reopened")
    return await _changed(db, request, background, user, alarm_id)


@router.get("/{alarm_id}/timeline", response_model=list[TimelineItem],
            summary="Linha do tempo do chamado: abertura, atendimento, anotações, avisos e normalização")
async def timeline(alarm_id: UUID, user: User, db: TenantDb) -> list[TimelineItem]:
    alarm = await db.fetchrow("SELECT created_at, cleared_at FROM alarms WHERE id = $1", alarm_id)
    if alarm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alarme não encontrado")
    items = [TimelineItem(at=alarm["created_at"], kind="opened")]
    owner = None
    for e in await db.fetch(
            "SELECT e.kind, e.body, e.created_at, e.target_id, ua.name AS actor, ut.name AS target "
            "FROM alarm_events e LEFT JOIN users ua ON ua.id = e.actor_id "
            "LEFT JOIN users ut ON ut.id = e.target_id WHERE e.alarm_id = $1 ORDER BY e.created_at", alarm_id):
        kind = e["kind"]
        if kind == "assigned":
            kind = "transferred" if owner is not None else "assigned"
            owner = e["target_id"]
        items.append(TimelineItem(at=e["created_at"], kind=kind, actor=e["actor"], target=e["target"], body=e["body"]))
    for n in await db.fetch(
            "SELECT n.sent_at, n.event, c.name FROM notifications n "
            "JOIN notification_channels c ON c.id = n.channel_id "
            "WHERE n.alarm_id = $1 AND n.status = 'sent' AND n.sent_at IS NOT NULL", alarm_id):
        items.append(TimelineItem(at=n["sent_at"], kind="notified", target=n["name"],
                                  body="normalização" if n["event"] == "cleared" else "abertura"))
    if alarm["cleared_at"]:
        items.append(TimelineItem(at=alarm["cleared_at"], kind="cleared"))
    return sorted(items, key=lambda i: i.at)
