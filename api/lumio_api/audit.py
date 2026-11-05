"""Log de auditoria: registra as ações que mudam o cadastro ou mexem no acesso.

Grava na mesma transação da ação: se a ação falhar (rollback), o registro
também some; o log só mostra o que de fato aconteceu.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import Request


def client_ip(request: Request | None) -> str | None:
    """IP de quem chamou. Na Vercel/atrás de proxy, o primeiro do X-Forwarded-For."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


async def audit(db: asyncpg.Connection, tenant_id: UUID, actor_id: UUID | None, action: str, *,
                request: Request | None = None, target_type: str | None = None, target_id: UUID | None = None,
                label: str | None = None, details: dict[str, Any] | None = None) -> None:
    await db.execute(
        "INSERT INTO audit_log (tenant_id, actor_id, actor_name, action, target_type, target_id, target_label, "
        "details, ip) VALUES ($1, $2, (SELECT name FROM users WHERE id = $2), $3, $4, $5, $6, $7::jsonb, $8)",
        tenant_id, actor_id, action, target_type, target_id, label,
        json.dumps(details or {}, default=str, ensure_ascii=False), client_ip(request),
    )
