"""Canais de notificação (e-mail e webhook) do provedor."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError, model_validator

from ..audit import audit
from ..deps import Admin, TenantDb, User, cipher
from ..schemas import Severity

router = APIRouter(prefix="/notification-channels", tags=["notificações"])

ChannelType = Literal["email", "webhook"]
_email = TypeAdapter(EmailStr)


def _check_target(type_: str, target: str) -> str:
    target = target.strip()
    if type_ == "email":
        try:
            return _email.validate_python(target)
        except ValidationError:
            raise ValueError("e-mail inválido")
    if not target.startswith(("https://", "http://")) or len(target) < 12:
        raise ValueError("URL do webhook deve começar com https:// (ou http:// em teste)")
    return target


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=80, examples=["NOC por e-mail"])
    type: ChannelType
    target: str = Field(min_length=3, max_length=500, examples=["noc@provedor.com.br"])
    min_severity: Severity = "major"
    notify_clear: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def valid_target(self):
        self.target = _check_target(self.type, self.target)
        return self


class ChannelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    target: str | None = Field(None, min_length=3, max_length=500)
    min_severity: Severity | None = None
    notify_clear: bool | None = None
    enabled: bool | None = None


class Delivery(BaseModel):
    id: UUID
    event: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
    alarm_kind: str | None
    alarm_severity: str | None


class ChannelOut(BaseModel):
    id: UUID
    name: str
    type: ChannelType
    target: str
    min_severity: Severity
    notify_clear: bool
    enabled: bool
    created_at: datetime
    last_delivery: Delivery | None


class ChannelCreated(BaseModel):
    channel: ChannelOut
    secret: str | None = Field(None, description="só webhook; aparece uma vez, guarde para conferir a assinatura")


SELECT = """
    SELECT c.*, d.id AS d_id, d.event AS d_event, d.status AS d_status, d.attempts AS d_attempts,
           d.last_error AS d_last_error, d.created_at AS d_created_at, d.sent_at AS d_sent_at,
           a.kind AS d_kind, a.severity AS d_severity
    FROM notification_channels c
    LEFT JOIN LATERAL (SELECT * FROM notifications n WHERE n.channel_id = c.id AND n.status <> 'suppressed'
                       ORDER BY n.created_at DESC LIMIT 1) d ON true
    LEFT JOIN alarms a ON a.id = d.alarm_id
"""


def to_out(r: asyncpg.Record) -> ChannelOut:
    last = None
    if r["d_id"]:
        last = Delivery(id=r["d_id"], event=r["d_event"], status=r["d_status"], attempts=r["d_attempts"],
                        last_error=r["d_last_error"], created_at=r["d_created_at"], sent_at=r["d_sent_at"],
                        alarm_kind=r["d_kind"], alarm_severity=r["d_severity"])
    return ChannelOut(**{k: r[k] for k in ChannelOut.model_fields if k != "last_delivery"}, last_delivery=last)


async def _get(db: asyncpg.Connection, channel_id: UUID) -> asyncpg.Record:
    row = await db.fetchrow(SELECT + " WHERE c.id = $1", channel_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canal não encontrado")
    return row


@router.get("", response_model=list[ChannelOut])
async def list_channels(user: User, db: TenantDb) -> list[ChannelOut]:
    return [to_out(r) for r in await db.fetch(SELECT + " ORDER BY c.name")]


@router.post("", response_model=ChannelCreated, status_code=status.HTTP_201_CREATED)
async def create_channel(body: ChannelIn, user: Admin, db: TenantDb, request: Request) -> ChannelCreated:
    secret = secrets.token_urlsafe(32) if body.type == "webhook" else None
    try:
        channel_id = await db.fetchval(
            "INSERT INTO notification_channels (tenant_id, name, type, target, secret_enc, min_severity, notify_clear, enabled) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
            user.tenant_id, body.name.strip(), body.type, body.target,
            cipher(request).encrypt(secret) if secret else None, body.min_severity, body.notify_clear, body.enabled)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status.HTTP_409_CONFLICT, f"já existe um canal chamado {body.name!r}")
    await audit(db, user.tenant_id, user.user_id, "channel.create", request=request, target_type="channel",
                target_id=channel_id, label=body.name.strip(),
                details={"type": body.type, "target": body.target, "min_severity": body.min_severity})
    return ChannelCreated(channel=to_out(await _get(db, channel_id)), secret=secret)


@router.patch("/{channel_id}", response_model=ChannelOut)
async def update_channel(channel_id: UUID, body: ChannelUpdate, user: Admin, db: TenantDb,
                         request: Request) -> ChannelOut:
    current = await _get(db, channel_id)
    changes = body.model_dump(exclude_none=True)
    if "target" in changes:
        try:
            changes["target"] = _check_target(current["type"], changes["target"])
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    if changes:
        cols = list(changes)
        sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(cols, 2))
        try:
            await db.execute(f"UPDATE notification_channels SET {sets} WHERE id = $1", channel_id, *changes.values())
        except asyncpg.UniqueViolationError:
            raise HTTPException(status.HTTP_409_CONFLICT, "já existe um canal com esse nome")
        await audit(db, user.tenant_id, user.user_id, "channel.update", request=request, target_type="channel",
                    target_id=channel_id, label=changes.get("name", current["name"]), details=changes)
    return to_out(await _get(db, channel_id))


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: UUID, user: Admin, db: TenantDb, request: Request) -> Response:
    gone = await db.fetchrow("DELETE FROM notification_channels WHERE id = $1 RETURNING name, type, target", channel_id)
    if gone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canal não encontrado")
    await audit(db, user.tenant_id, user.user_id, "channel.delete", request=request, target_type="channel",
                target_id=channel_id, label=gone["name"], details={"type": gone["type"], "target": gone["target"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{channel_id}/rotate-secret", response_model=ChannelCreated,
             summary="Gera um segredo novo para o webhook (o antigo para de valer)")
async def rotate_secret(channel_id: UUID, user: Admin, db: TenantDb, request: Request) -> ChannelCreated:
    row = await _get(db, channel_id)
    if row["type"] != "webhook":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "só webhook tem segredo")
    secret = secrets.token_urlsafe(32)
    await db.execute("UPDATE notification_channels SET secret_enc = $2 WHERE id = $1",
                     channel_id, cipher(request).encrypt(secret))
    await audit(db, user.tenant_id, user.user_id, "channel.rotate_secret", request=request, target_type="channel",
                target_id=channel_id, label=row["name"])
    return ChannelCreated(channel=to_out(row), secret=secret)


@router.post("/{channel_id}/test", response_model=Delivery, status_code=status.HTTP_202_ACCEPTED,
             summary="Põe uma mensagem de teste na fila; acompanhe em /deliveries")
async def test_channel(channel_id: UUID, user: User, db: TenantDb) -> Delivery:
    await _get(db, channel_id)
    row = await db.fetchrow(
        "INSERT INTO notifications (tenant_id, channel_id, event) VALUES ($1, $2, 'test') "
        "RETURNING id, event, status, attempts, last_error, created_at, sent_at", user.tenant_id, channel_id)
    return Delivery(**dict(row), alarm_kind=None, alarm_severity=None)


@router.get("/{channel_id}/deliveries", response_model=list[Delivery], summary="Últimas entregas do canal")
async def deliveries(channel_id: UUID, user: User, db: TenantDb,
                     limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[Delivery]:
    await _get(db, channel_id)
    rows = await db.fetch(
        "SELECT n.id, n.event, n.status, n.attempts, n.last_error, n.created_at, n.sent_at, "
        "a.kind AS alarm_kind, a.severity AS alarm_severity "
        "FROM notifications n LEFT JOIN alarms a ON a.id = n.alarm_id WHERE n.channel_id = $1 "
        f"ORDER BY n.created_at DESC LIMIT {int(limit)}", channel_id)
    return [Delivery(**dict(r)) for r in rows]
