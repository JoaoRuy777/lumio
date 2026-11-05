"""Consulta do log de auditoria (só administradores)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from ..deps import Admin, TenantDb

router = APIRouter(prefix="/audit-log", tags=["auditoria"])

ACTION_LABEL = {
    "auth.signup": "Criou a conta do provedor",
    "auth.login": "Entrou no sistema",
    "auth.login_failed": "Errou a senha ao entrar",
    "auth.login_blocked": "Login travado (muitas tentativas)",
    "auth.password_changed": "Trocou a própria senha",
    "auth.password_reset": "Redefiniu a senha pelo e-mail",
    "user.create": "Criou usuário",
    "user.delete": "Removeu usuário",
    "olt.create": "Cadastrou OLT",
    "olt.update": "Alterou OLT",
    "olt.delete": "Removeu OLT",
    "channel.create": "Criou canal de notificação",
    "channel.update": "Alterou canal de notificação",
    "channel.delete": "Removeu canal de notificação",
    "channel.rotate_secret": "Gerou novo segredo do webhook",
    "escalation.create": "Criou regra de escalonamento",
    "escalation.update": "Alterou regra de escalonamento",
    "escalation.delete": "Apagou regra de escalonamento",
    "maintenance.create": "Agendou manutenção",
    "maintenance.end": "Encerrou manutenção antes da hora",
    "maintenance.cancel": "Cancelou manutenção",
    "customer.import": "Importou clientes (CSV)",
    "customer.delete": "Removeu cliente",
}

Category = Literal["auth", "user", "olt", "channel", "escalation", "maintenance", "customer"]


class AuditEntry(BaseModel):
    id: UUID
    at: datetime
    actor_id: UUID | None
    actor_name: str | None
    action: str
    action_label: str
    target_type: str | None
    target_id: UUID | None
    target_label: str | None
    details: dict[str, Any]
    ip: str | None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int


def _where(category: str | None, actor_id: UUID | None, q: str | None, start: datetime | None,
           end: datetime | None) -> tuple[str, list]:
    conds, args = [], []
    if category:
        args.append(category + ".%")
        conds.append(f"action LIKE ${len(args)}")
    if actor_id:
        args.append(actor_id)
        conds.append(f"actor_id = ${len(args)}")
    if q:
        args.append(f"%{q.lower()}%")
        conds.append(f"(lower(coalesce(target_label, '')) LIKE ${len(args)} OR lower(coalesce(actor_name, '')) LIKE ${len(args)}"
                     f" OR lower(details::text) LIKE ${len(args)})")
    if start:
        args.append(start)
        conds.append(f"at >= ${len(args)}")
    if end:
        args.append(end)
        conds.append(f"at < ${len(args)}")
    return (" WHERE " + " AND ".join(conds)) if conds else "", args


def _entry(row) -> AuditEntry:
    data = dict(row)
    data["details"] = json.loads(data["details"]) if isinstance(data["details"], str) else data["details"]
    data["action_label"] = ACTION_LABEL.get(data["action"], data["action"])
    return AuditEntry(**data)


@router.get("", response_model=AuditPage, summary="Quem fez o quê: mais recente primeiro")
async def list_audit(
    user: Admin, db: TenantDb,
    category: Category | None = None,
    actor_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    where, args = _where(category, actor_id, q, start, end)
    total = await db.fetchval("SELECT count(*) FROM audit_log" + where, *args)
    rows = await db.fetch(
        f"SELECT * FROM audit_log{where} ORDER BY at DESC, id LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}",
        *args, limit, offset)
    return AuditPage(items=[_entry(r) for r in rows], total=total)


@router.get("/export.csv", summary="Exporta o log filtrado em CSV (até 10 mil linhas)",
            response_class=Response, responses={200: {"content": {"text/csv": {}}}})
async def export_audit(
    user: Admin, db: TenantDb,
    category: Category | None = None,
    actor_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
) -> Response:
    where, args = _where(category, actor_id, q, start, end)
    rows = await db.fetch(f"SELECT * FROM audit_log{where} ORDER BY at DESC, id LIMIT 10000", *args)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["quando (UTC)", "quem", "ação", "alvo", "detalhes", "ip"])
    for r in map(_entry, rows):
        w.writerow([r.at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), r.actor_name or "", r.action_label,
                    r.target_label or "", json.dumps(r.details, ensure_ascii=False) if r.details else "", r.ip or ""])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="auditoria-lumio-{stamp}.csv"'})
