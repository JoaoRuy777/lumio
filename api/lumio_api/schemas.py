"""Formato das requisições e respostas da API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

# ------------------------------------------------------------------ auth


class SignupIn(BaseModel):
    company: str = Field(min_length=2, max_length=120, examples=["Provedor Exemplo"])
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PlanUsage(BaseModel):
    used: int
    limit: int


class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=120, examples=["Maria Souza"])
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    role: Literal["admin", "operator"] = "operator"


class UserOut(BaseModel):
    id: UUID
    name: str
    email: str
    role: str
    created_at: datetime


class UserList(BaseModel):
    items: list[UserOut]


class MeOut(BaseModel):
    user_id: UUID
    email: str
    name: str
    role: str
    tenant_id: UUID
    tenant_name: str
    olts: PlanUsage

# ------------------------------------------------------------------ OLTs


class SnmpAccess(BaseModel):
    host: str = Field(min_length=1, max_length=255, examples=["10.0.0.2"])
    snmp_port: int = Field(161, ge=1, le=65535)
    community: str = Field(min_length=1, max_length=100)

    @field_validator("host")
    @classmethod
    def no_spaces(cls, v: str) -> str:
        v = v.strip()
        if " " in v:
            raise ValueError("host não pode ter espaços")
        return v


class OltCreate(SnmpAccess):
    name: str = Field(min_length=1, max_length=80, examples=["olt-centro"])
    status_interval_s: int = Field(60, ge=30, le=3600)
    optical_interval_s: int = Field(300, ge=60, le=86400)
    enabled: bool = True
    lat: float | None = Field(None, ge=-90, le=90, description="localização no mapa (opcional)")
    lon: float | None = Field(None, ge=-180, le=180)


class OltUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    host: str | None = Field(None, min_length=1, max_length=255)
    snmp_port: int | None = Field(None, ge=1, le=65535)
    community: str | None = Field(None, min_length=1, max_length=100)   # vazio = mantém a atual
    status_interval_s: int | None = Field(None, ge=30, le=3600)
    optical_interval_s: int | None = Field(None, ge=60, le=86400)
    enabled: bool | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)


CollectionStatus = Literal["ok", "error", "pending", "late", "disabled"]


class OltOut(BaseModel):
    id: UUID
    name: str
    host: str | None
    snmp_port: int
    vendor: str | None
    model: str | None
    sys_name: str | None
    status_interval_s: int
    optical_interval_s: int
    enabled: bool
    has_community: bool          # a community nunca sai da API
    collection_status: CollectionStatus
    last_poll_at: datetime | None
    last_error: str | None
    discovered_at: datetime | None
    pon_ports: int
    onus_total: int
    onus_online: int
    active_alarms: int
    lat: float | None
    lon: float | None


class OltList(BaseModel):
    items: list[OltOut]
    usage: PlanUsage


class ConnectionTest(BaseModel):
    ok: bool
    vendor: str | None = None
    model: str | None = None
    sys_name: str | None = None
    pon_ports: list[str] = []
    onus: int | None = None
    error: str | None = None


class DiscoveryOut(BaseModel):
    ok: bool
    pon_ports: int = 0
    onus: int = 0
    onus_online: int = 0        # no momento da descoberta (o painel mostra o da última coleta)
    error: str | None = None


class OltSaved(BaseModel):
    olt: OltOut
    discovery: DiscoveryOut

# ------------------------------------------------------------------ coletor


class CollectorOlt(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    host: str
    snmp_port: int
    community: str
    vendor: str | None
    sys_name: str | None
    status_interval_s: int
    optical_interval_s: int

# ------------------------------------------------------------------ painel (sprint 4)

Severity = Literal["critical", "major", "minor", "warning"]
AlarmStatus = Literal["active", "acknowledged", "cleared"]


class PonOut(BaseModel):
    id: UUID
    name: str
    onus_total: int
    onus_online: int
    rx_avg: float | None
    rx_min: float | None
    active_alarms: int


class OnuOut(BaseModel):
    id: UUID
    olt_id: UUID
    olt_name: str
    pon_id: UUID
    pon: str
    onu_index: int
    serial: str | None
    online: bool | None          # None = ainda não coletado
    rx_dbm: float | None
    tx_dbm: float | None
    last_change_at: datetime | None
    last_seen_at: datetime | None
    active_alarms: list[str]     # tipos dos alarmes abertos


class OnuPage(BaseModel):
    items: list[OnuOut]
    total: int


class Reading(BaseModel):
    ts: datetime
    rx_dbm: float | None
    tx_dbm: float | None


class Readings(BaseModel):
    items: list[Reading]
    bucket_s: int                # 0 = leituras cruas; >0 = média por intervalo


class AlarmOut(BaseModel):
    id: UUID
    kind: str
    severity: Severity
    status: AlarmStatus
    source: str
    olt_id: UUID
    olt_name: str
    pon_id: UUID | None
    pon: str | None
    onu_id: UUID | None
    onu_index: int | None
    onu_serial: str | None
    parent_id: UUID | None
    children: int                # ONUs agrupadas sob um rompimento de fibra
    occurrences: int
    details: dict
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    cleared_at: datetime | None
    latency_ms: float | None
    acknowledged_at: datetime | None
    acknowledged_by: str | None  # nome de quem reconheceu
    # atendimento (chamado)
    assigned_to_id: UUID | None
    assigned_to: str | None      # nome de quem está com o chamado
    assigned_at: datetime | None
    first_assigned_at: datetime | None
    work_closed_at: datetime | None
    work_closed_by: str | None
    resolution_cause: str | None
    resolution_notes: str | None
    customer_name: str | None    # cliente da ONU (alarmes de ONU)
    affected_customers: int      # clientes nas ONUs de um rompimento


Cause = Literal["fiber_third_party", "fiber_natural", "power", "equipment", "customer",
                "maintenance", "configuration", "no_fault", "other"]


class AssignIn(BaseModel):
    user_id: UUID | None = Field(None, description="vazio: assumir para si; preenchido: transferir")


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CloseIn(BaseModel):
    cause: Cause
    notes: str = Field(min_length=3, max_length=4000, description="o que foi feito")


class TimelineItem(BaseModel):
    at: datetime
    kind: Literal["opened", "assigned", "transferred", "note", "closed", "reopened", "notified", "cleared"]
    actor: str | None = None
    target: str | None = None
    body: str | None = None


class AlarmPage(BaseModel):
    items: list[AlarmOut]
    total: int


class Overview(BaseModel):
    olts: dict[str, int]         # total + contagem por status da coleta
    onus: dict[str, int]         # total, online, offline, unknown
    rx_low: int                  # ONUs com sinal abaixo do limite
    rx_trend: int = 0            # ONUs com sinal piorando (devem passar do limite em até 7 dias)
    customers: int = 0           # clientes importados
    customers_offline: int = 0   # clientes com a ONU offline agora
    alarms: dict[str, int]       # abertos (sem os agrupados) por severidade + total
    recent_alarms: list[AlarmOut]


class HourPoint(BaseModel):
    t: datetime                  # início da hora
    critical: int                # alarmes abertos nesta hora, por severidade
    major: int
    other: int                   # menor + aviso
    open: int                    # alarmes em aberto ao fim da hora
    onus_offline: int            # ONUs offline ao fim da hora


class OverviewHistory(BaseModel):
    hours: list[HourPoint]       # 24 pontos, do mais antigo para agora
