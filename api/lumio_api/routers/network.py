"""Rede do provedor: PONs de uma OLT, ONUs (com filtros) e histórico de potência."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Query, status

from ..deps import TenantDb, User
from ..schemas import OnuOut, OnuPage, PonOut, Reading, Readings

router = APIRouter(tags=["rede"])

ONU_SELECT = """
    SELECT n.*, o.name AS olt_name, p.name AS pon,
           COALESCE((SELECT array_agg(DISTINCT a.kind) FROM alarms a
                     WHERE a.onu_id = n.id AND a.status <> 'cleared'), '{}') AS active_alarms
    FROM onus n
    JOIN olts o ON o.id = n.olt_id
    JOIN pon_ports p ON p.id = n.pon_id
"""

# Mostra no máximo ~300 pontos no gráfico: acima disso, média por intervalo
MAX_POINTS = 300
RAW_STEP = timedelta(minutes=5)          # intervalo padrão da coleta de potência


def to_onu(row: asyncpg.Record) -> OnuOut:
    return OnuOut(**{k: row[k] for k in OnuOut.model_fields})


@router.get("/olts/{olt_id}/pons", response_model=list[PonOut], summary="Portas PON da OLT com resumo das ONUs")
async def list_pons(olt_id: UUID, user: User, db: TenantDb) -> list[PonOut]:
    if not await db.fetchval("SELECT 1 FROM olts WHERE id = $1", olt_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OLT não encontrada")
    rows = await db.fetch(
        """
        SELECT p.id, p.name,
               count(n.id) AS onus_total, count(n.id) FILTER (WHERE n.online) AS onus_online,
               round(avg(n.rx_dbm) FILTER (WHERE n.online)::numeric, 2)::float AS rx_avg,
               min(n.rx_dbm) FILTER (WHERE n.online) AS rx_min,
               (SELECT count(*) FROM alarms a WHERE a.pon_id = p.id AND a.status <> 'cleared'
                  AND a.parent_id IS NULL) AS active_alarms
        FROM pon_ports p LEFT JOIN onus n ON n.pon_id = p.id
        WHERE p.olt_id = $1 GROUP BY p.id ORDER BY p.name
        """, olt_id)
    return [PonOut(**dict(r)) for r in rows]


@router.get("/onus", response_model=OnuPage, summary="ONUs do provedor, com filtros")
async def list_onus(
    user: User, db: TenantDb,
    olt_id: UUID | None = None,
    pon_id: UUID | None = None,
    state: Annotated[Literal["online", "offline", "unknown"] | None, Query(alias="status")] = None,
    rx_below: Annotated[float | None, Query(description="só ONUs com sinal abaixo deste valor (dBm)")] = None,
    q: Annotated[str | None, Query(max_length=40, description="busca por serial")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OnuPage:
    where, args = [], []

    def add(cond: str, value) -> None:
        args.append(value)
        where.append(cond.replace("?", f"${len(args)}"))

    if olt_id:
        add("n.olt_id = ?", olt_id)
    if pon_id:
        add("n.pon_id = ?", pon_id)
    if state == "online":
        where.append("n.online")
    elif state == "offline":
        where.append("n.online IS FALSE")
    elif state == "unknown":
        where.append("n.online IS NULL")
    if rx_below is not None:
        add("n.rx_dbm < ?", rx_below)
    if q:
        add("n.serial ILIKE ?", f"%{q.strip()}%")
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    total = await db.fetchval("SELECT count(*) FROM onus n" + cond, *args)
    # offline primeiro (é o que o operador procura), depois por posição na rede
    rows = await db.fetch(f"{ONU_SELECT}{cond} ORDER BY n.online NULLS FIRST, o.name, p.name, n.onu_index "
                          f"LIMIT {int(limit)} OFFSET {int(offset)}", *args)
    return OnuPage(items=[to_onu(r) for r in rows], total=total)


@router.get("/onus/{onu_id}", response_model=OnuOut)
async def get_onu(onu_id: UUID, user: User, db: TenantDb) -> OnuOut:
    row = await db.fetchrow(ONU_SELECT + " WHERE n.id = $1", onu_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ONU não encontrada")
    return to_onu(row)


@router.get("/onus/{onu_id}/readings", response_model=Readings, summary="Histórico de potência óptica")
async def onu_readings(onu_id: UUID, user: User, db: TenantDb,
                       hours: Annotated[int, Query(ge=1, le=24 * 90)] = 24) -> Readings:
    if not await db.fetchval("SELECT 1 FROM onus WHERE id = $1", onu_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ONU não encontrada")
    span = timedelta(hours=hours)
    bucket = span / MAX_POINTS
    if bucket <= RAW_STEP:
        rows = await db.fetch(
            "SELECT ts, rx_dbm, tx_dbm FROM optical_readings WHERE onu_id = $1 AND ts >= now() - $2::interval "
            "ORDER BY ts", onu_id, span)
        return Readings(items=[Reading(**dict(r)) for r in rows], bucket_s=0)
    rows = await db.fetch(
        "SELECT date_bin($3::interval, ts, '2000-01-01') AS ts, avg(rx_dbm)::float AS rx_dbm, avg(tx_dbm)::float AS tx_dbm "
        "FROM optical_readings WHERE onu_id = $1 AND ts >= now() - $2::interval GROUP BY 1 ORDER BY 1",
        onu_id, span, bucket)
    return Readings(items=[Reading(**dict(r)) for r in rows], bucket_s=int(bucket.total_seconds()))
