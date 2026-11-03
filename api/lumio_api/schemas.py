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


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PlanUsage(BaseModel):
    used: int
    limit: int


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


class OltUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    host: str | None = Field(None, min_length=1, max_length=255)
    snmp_port: int | None = Field(None, ge=1, le=65535)
    community: str | None = Field(None, min_length=1, max_length=100)   # vazio = mantém a atual
    status_interval_s: int | None = Field(None, ge=30, le=3600)
    optical_interval_s: int | None = Field(None, ge=60, le=86400)
    enabled: bool | None = None


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
