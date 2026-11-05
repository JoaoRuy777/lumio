"""Cadastro de OLTs. Todas as consultas rodam com app.tenant_id do usuário:
o RLS garante que um provedor não lê nem altera OLT de outro."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Request, Response, status

from .. import snmp
from ..audit import audit
from ..deps import Admin, TenantDb, User, cipher, settings
from ..schemas import (ConnectionTest, DiscoveryOut, OltCreate, OltList, OltOut, OltSaved, OltUpdate, PlanUsage,
                       SnmpAccess)

router = APIRouter(prefix="/olts", tags=["OLTs"])

OLT_SELECT = """
    SELECT o.*, o.community_enc IS NOT NULL AS has_community,
        (SELECT count(*) FROM pon_ports p WHERE p.olt_id = o.id) AS pon_ports,
        (SELECT count(*) FROM onus n WHERE n.olt_id = o.id) AS onus_total,
        (SELECT count(*) FROM onus n WHERE n.olt_id = o.id AND n.online) AS onus_online,
        (SELECT count(*) FROM alarms a WHERE a.olt_id = o.id AND a.status <> 'cleared') AS active_alarms
    FROM olts o
"""

# Coleta "atrasada" se o último polling tem mais que este múltiplo do intervalo
LATE_FACTOR = 3


def collection_status(row: asyncpg.Record, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if not row["enabled"]:
        return "disabled"
    if row["reachable"] is False:
        return "error"
    if row["last_poll_at"] is None:
        return "pending"
    if now - row["last_poll_at"] > timedelta(seconds=LATE_FACTOR * row["status_interval_s"]):
        return "late"
    return "ok"


def to_out(row: asyncpg.Record) -> OltOut:
    data = {k: row[k] for k in OltOut.model_fields if k != "collection_status"}
    return OltOut(**data, collection_status=collection_status(row))


async def _get(db: asyncpg.Connection, olt_id: UUID) -> asyncpg.Record:
    row = await db.fetchrow(OLT_SELECT + " WHERE o.id = $1", olt_id)
    if row is None:
        # 404 também para OLT de outro tenant: nem confirma que ela existe
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OLT não encontrada")
    return row


async def _usage(db: asyncpg.Connection, lock: bool = False) -> PlanUsage:
    limit = await db.fetchval("SELECT olt_limit FROM tenants" + (" FOR UPDATE" if lock else ""))
    used = await db.fetchval("SELECT count(*) FROM olts")
    return PlanUsage(used=used, limit=limit)


async def _discover(request: Request, db: asyncpg.Connection, olt_id: UUID, tenant_id: UUID,
                    host: str, port: int, community: str) -> DiscoveryOut:
    """Identifica a OLT e grava as PONs e ONUs encontradas."""
    cfg = settings(request)
    found = await snmp.discover(request.app.state.snmp, host, port, community, cfg.snmp_timeout, cfg.snmp_retries)
    if not found["ok"]:
        await db.execute("UPDATE olts SET last_error = $2 WHERE id = $1", olt_id, found["error"])
        return DiscoveryOut(ok=False, error=found["error"])

    await db.execute(
        "UPDATE olts SET vendor = $2, model = $3, sys_name = $4, discovered_at = now(), last_error = NULL "
        "WHERE id = $1", olt_id, found["vendor"], found["model"], found["sys_name"])
    pons: dict[str, UUID] = {}
    for name in sorted(set(found["pon_ports"]) | {o["pon"] for o in found["onu_list"]}):
        pons[name] = await db.fetchval(
            "INSERT INTO pon_ports (tenant_id, olt_id, name) VALUES ($1, $2, $3) "
            "ON CONFLICT (olt_id, name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            tenant_id, olt_id, name)
    # A descoberta grava só o inventário; o estado online fica NULL (desconhecido).
    # Quem decide online/offline é o worker, na primeira coleta: se a ONU já
    # estiver offline, "desconhecido -> offline" abre o alarme. Gravar o estado
    # aqui faria o worker não ver transição e nunca alarmar essa ONU.
    await db.executemany(
        "INSERT INTO onus (tenant_id, olt_id, pon_id, onu_index, serial) VALUES ($1, $2, $3, $4, $5) "
        "ON CONFLICT (pon_id, onu_index) DO UPDATE SET serial = EXCLUDED.serial",
        [(tenant_id, olt_id, pons[o["pon"]], o["onu"], o["serial"]) for o in found["onu_list"]])
    return DiscoveryOut(ok=True, pon_ports=len(pons), onus=len(found["onu_list"]),
                        onus_online=sum(o["online"] for o in found["onu_list"]))


@router.get("", response_model=OltList, summary="Lista as OLTs do provedor, com status da coleta e uso do plano")
async def list_olts(user: User, db: TenantDb) -> OltList:
    rows = await db.fetch(OLT_SELECT + " ORDER BY o.name")
    return OltList(items=[to_out(r) for r in rows], usage=await _usage(db))


@router.post("/test-connection", response_model=ConnectionTest,
             summary="Testar conexão: detecta fabricante, modelo, PONs e ONUs sem salvar nada")
async def test_connection(body: SnmpAccess, user: User, request: Request) -> ConnectionTest:
    cfg = settings(request)
    return ConnectionTest(**await snmp.test_connection(request.app.state.snmp, body.host, body.snmp_port,
                                                       body.community, cfg.snmp_timeout, cfg.snmp_retries))


@router.post("", response_model=OltSaved, status_code=status.HTTP_201_CREATED,
             summary="Cadastra a OLT e já descobre as portas PON e as ONUs")
async def create_olt(body: OltCreate, user: Admin, db: TenantDb, request: Request) -> OltSaved:
    usage = await _usage(db, lock=True)
    if usage.used >= usage.limit:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"limite do plano atingido ({usage.used} de {usage.limit} OLTs)")
    try:
        olt_id = await db.fetchval(
            "INSERT INTO olts (tenant_id, name, host, snmp_port, community_enc, status_interval_s, "
            "optical_interval_s, enabled, lat, lon) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id",
            user.tenant_id, body.name.strip(), body.host, body.snmp_port, cipher(request).encrypt(body.community),
            body.status_interval_s, body.optical_interval_s, body.enabled, body.lat, body.lon)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status.HTTP_409_CONFLICT, f"já existe uma OLT chamada {body.name!r}")
    discovery = await _discover(request, db, olt_id, user.tenant_id, body.host, body.snmp_port, body.community)
    await audit(db, user.tenant_id, user.user_id, "olt.create", request=request, target_type="olt", target_id=olt_id,
                label=body.name.strip(), details={"host": body.host, "snmp_port": body.snmp_port})
    return OltSaved(olt=to_out(await _get(db, olt_id)), discovery=discovery)


@router.get("/{olt_id}", response_model=OltOut)
async def get_olt(olt_id: UUID, user: User, db: TenantDb) -> OltOut:
    return to_out(await _get(db, olt_id))


@router.patch("/{olt_id}", response_model=OltSaved,
              summary="Altera a OLT; se mudar o acesso SNMP, refaz a descoberta")
async def update_olt(olt_id: UUID, body: OltUpdate, user: Admin, db: TenantDb, request: Request) -> OltSaved:
    current = await _get(db, olt_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    # no log: o que mudou, sem o valor da community (segredo)
    logged = {k: ("(alterada)" if k == "community" else v) for k, v in changes.items()}
    if "community" in changes:
        changes["community_enc"] = cipher(request).encrypt(changes.pop("community"))
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    if changes:
        cols = list(changes)
        sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(cols, 2))
        try:
            await db.execute(f"UPDATE olts SET {sets} WHERE id = $1", olt_id, *(changes[c] for c in cols))
        except asyncpg.UniqueViolationError:
            raise HTTPException(status.HTTP_409_CONFLICT, f"já existe uma OLT chamada {changes['name']!r}")

    discovery = DiscoveryOut(ok=True)
    if {"host", "snmp_port", "community_enc"} & set(changes):
        row = await db.fetchrow("SELECT host, snmp_port, community_enc FROM olts WHERE id = $1", olt_id)
        discovery = await _discover(request, db, olt_id, current["tenant_id"], row["host"], row["snmp_port"],
                                    cipher(request).decrypt(row["community_enc"]))
    if logged:
        name = await db.fetchval("SELECT name FROM olts WHERE id = $1", olt_id)
        await audit(db, user.tenant_id, user.user_id, "olt.update", request=request, target_type="olt",
                    target_id=olt_id, label=name, details=logged)
    return OltSaved(olt=to_out(await _get(db, olt_id)), discovery=discovery)


@router.delete("/{olt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_olt(olt_id: UUID, user: Admin, db: TenantDb, request: Request) -> Response:
    gone = await db.fetchrow("DELETE FROM olts WHERE id = $1 RETURNING name, host", olt_id)
    if gone is not None:
        await audit(db, user.tenant_id, user.user_id, "olt.delete", request=request, target_type="olt",
                    target_id=olt_id, label=gone["name"], details={"host": gone["host"]})
    if gone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OLT não encontrada")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{olt_id}/test-connection", response_model=ConnectionTest,
             summary="Testar conexão de uma OLT já cadastrada, com a community salva")
async def test_saved_connection(olt_id: UUID, user: User, db: TenantDb, request: Request) -> ConnectionTest:
    row = await _get(db, olt_id)
    cfg = settings(request)
    return ConnectionTest(**await snmp.test_connection(
        request.app.state.snmp, row["host"], row["snmp_port"], cipher(request).decrypt(row["community_enc"]),
        cfg.snmp_timeout, cfg.snmp_retries))


@router.post("/{olt_id}/discover", response_model=DiscoveryOut, summary="Refaz a descoberta de PONs e ONUs")
async def rediscover(olt_id: UUID, user: Admin, db: TenantDb, request: Request) -> DiscoveryOut:
    row = await _get(db, olt_id)
    return await _discover(request, db, olt_id, row["tenant_id"], row["host"], row["snmp_port"],
                           cipher(request).decrypt(row["community_enc"]))
