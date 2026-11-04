"""Clientes (importados por CSV, ligados à ONU pelo serial) e o mapa da rede."""

from __future__ import annotations

import csv
import io
import unicodedata
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from .. import trend
from ..deps import Admin, TenantDb, User

router = APIRouter(tags=["clientes e mapa"])

State = Literal["online", "offline", "low", "trend", "unknown"]


class CustomerOut(BaseModel):
    id: UUID
    code: str | None
    name: str
    phone: str | None
    address: str | None
    district: str | None
    city: str | None
    plan: str | None
    lat: float | None
    lon: float | None
    serial: str
    onu_id: UUID | None          # None: nenhuma ONU com esse serial (ainda)
    olt_id: UUID | None
    olt_name: str | None
    pon: str | None
    onu_index: int | None
    rx_dbm: float | None
    state: State
    ticket_id: UUID | None       # chamado aberto que afeta o cliente (o rompimento, se houver)


class CustomerPage(BaseModel):
    items: list[CustomerOut]
    total: int


class ImportIn(BaseModel):
    csv: str = Field(min_length=1, max_length=5_000_000)


class ImportError_(BaseModel):
    line: int
    error: str


class ImportResult(BaseModel):
    created: int
    updated: int
    unmatched: int               # clientes cujo serial não bate com nenhuma ONU coletada
    errors: list[ImportError_]


class MapOlt(BaseModel):
    id: UUID
    name: str
    lat: float | None
    lon: float | None
    located: bool                # False: posição estimada pelo centro dos clientes
    reachable: bool | None
    onus_total: int
    onus_online: int
    open_alarms: int


class MapOut(BaseModel):
    olts: list[MapOlt]
    customers: list[CustomerOut]


CUSTOMER_SELECT = """
    WITH open_tickets AS (
        SELECT DISTINCT ON (a.onu_id) a.onu_id, coalesce(a.parent_id, a.id) AS ticket_id
        FROM alarms a WHERE a.status <> 'cleared' AND a.onu_id IS NOT NULL
        ORDER BY a.onu_id, a.created_at DESC
    ), risk AS ({trend})
    SELECT c.*, c.onu_serial AS serial, n.id AS onu_id, n.olt_id, o.name AS olt_name, p.name AS pon, n.onu_index,
           n.rx_dbm, ot.ticket_id,
           CASE WHEN n.id IS NULL OR n.online IS NULL THEN 'unknown'
                WHEN NOT n.online THEN 'offline'
                WHEN n.rx_dbm < {limit} THEN 'low'
                WHEN risk.onu_id IS NOT NULL THEN 'trend'
                ELSE 'online' END AS state
    FROM customers c
    LEFT JOIN onus n ON n.tenant_id = c.tenant_id AND n.serial = c.onu_serial
    LEFT JOIN olts o ON o.id = n.olt_id
    LEFT JOIN pon_ports p ON p.id = n.pon_id
    LEFT JOIN open_tickets ot ON ot.onu_id = n.id
    LEFT JOIN risk ON risk.onu_id = n.id
""".format(trend=trend.TREND_SQL, limit=trend.RX_LIMIT_DBM)


def to_customer(row: asyncpg.Record) -> CustomerOut:
    return CustomerOut(**{k: row[k] for k in CustomerOut.model_fields})


@router.get("/customers", response_model=CustomerPage, summary="Clientes, com o estado da ONU de cada um")
async def list_customers(
    user: User, db: TenantDb,
    q: Annotated[str | None, Query(max_length=100, description="nome, código, serial, endereço ou bairro")] = None,
    state: State | None = None,
    olt_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerPage:
    where, args = [], []
    if q:
        args.append(f"%{q.strip().lower()}%")
        n = len(args)
        where.append(f"(lower(x.name) LIKE ${n} OR lower(coalesce(x.code, '')) LIKE ${n} OR lower(x.serial) LIKE ${n} "
                     f"OR lower(coalesce(x.address, '')) LIKE ${n} OR lower(coalesce(x.district, '')) LIKE ${n})")
    if olt_id:
        args.append(olt_id)
        where.append(f"x.olt_id = ${len(args)}")
    if state:
        args.append(state)
        where.append(f"x.state = ${len(args)}")
    base = f"SELECT * FROM ({CUSTOMER_SELECT}) x"
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    total = await db.fetchval(f"SELECT count(*) FROM ({base}{cond}) y", *args)
    rows = await db.fetch(f"{base}{cond} ORDER BY lower(x.name) LIMIT {int(limit)} OFFSET {int(offset)}", *args)
    return CustomerPage(items=[to_customer(r) for r in rows], total=total)


@router.get("/onus/{onu_id}/customer", response_model=CustomerOut | None, summary="Cliente ligado à ONU")
async def onu_customer(onu_id: UUID, user: User, db: TenantDb) -> CustomerOut | None:
    row = await db.fetchrow(f"SELECT * FROM ({CUSTOMER_SELECT}) x WHERE x.onu_id = $1", onu_id)
    return to_customer(row) if row else None


# ------------------------------------------------------------------ importação

COLUMNS = {
    "serial": ("serial", "onu", "serial_onu", "onu_serial", "sn"),
    "name": ("nome", "name", "cliente", "nome_cliente"),
    "code": ("codigo", "code", "id_cliente", "contrato"),
    "phone": ("telefone", "phone", "celular", "fone"),
    "address": ("endereco", "address", "logradouro"),
    "district": ("bairro", "district"),
    "city": ("cidade", "city", "municipio"),
    "plan": ("plano", "plan"),
    "lat": ("latitude", "lat"),
    "lon": ("longitude", "lon", "lng"),
}


def _norm(header: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", header).encode("ascii", "ignore").decode()
    return ascii_.strip().lower().replace(" ", "_")


def _coord(value: str, lo: float, hi: float) -> float | None:
    if not value.strip():
        return None
    v = float(value.strip().replace(",", "."))
    if not lo <= v <= hi:
        raise ValueError(f"coordenada fora do intervalo: {value}")
    return v


def parse_csv(text: str) -> tuple[list[tuple[int, dict]], list[ImportError_]]:
    text = text.lstrip("﻿")
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, None)
    if not header:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "arquivo vazio")
    index = {}
    for i, h in enumerate(header):
        for field, aliases in COLUMNS.items():
            if _norm(h) in aliases and field not in index:
                index[field] = i
    if "serial" not in index or "name" not in index:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "o CSV precisa das colunas serial e nome (veja o modelo na tela de Clientes)")
    rows, errors = [], []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        get = lambda f: cells[index[f]].strip() if f in index and index[f] < len(cells) else ""  # noqa: E731
        try:
            serial, name = get("serial").upper(), get("name")
            if not serial or not name:
                raise ValueError("serial e nome são obrigatórios")
            rows.append((line_no, {
                "serial": serial, "name": name[:200], "code": get("code") or None, "phone": get("phone") or None,
                "address": get("address") or None, "district": get("district") or None, "city": get("city") or None,
                "plan": get("plan") or None, "lat": _coord(get("lat"), -90, 90), "lon": _coord(get("lon"), -180, 180),
            }))
        except ValueError as e:
            errors.append(ImportError_(line=line_no, error=str(e)))
    if len(rows) > 50_000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "máximo de 50 mil clientes por arquivo")
    return rows, errors


@router.post("/customers/import", response_model=ImportResult,
             summary="Importa clientes de um CSV (serial;nome;telefone;endereco;bairro;cidade;plano;latitude;longitude)")
async def import_customers(body: ImportIn, user: Admin, db: TenantDb) -> ImportResult:
    rows, errors = parse_csv(body.csv)
    created = updated = 0
    for _, r in rows:
        inserted = await db.fetchval(
            """
            INSERT INTO customers (tenant_id, onu_serial, code, name, phone, address, district, city, plan, lat, lon)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (tenant_id, onu_serial) DO UPDATE SET
                code = EXCLUDED.code, name = EXCLUDED.name, phone = EXCLUDED.phone, address = EXCLUDED.address,
                district = EXCLUDED.district, city = EXCLUDED.city, plan = EXCLUDED.plan,
                lat = EXCLUDED.lat, lon = EXCLUDED.lon, updated_at = now()
            RETURNING (xmax = 0)
            """, user.tenant_id, r["serial"], r["code"], r["name"], r["phone"], r["address"], r["district"],
            r["city"], r["plan"], r["lat"], r["lon"])
        created += inserted
        updated += not inserted
    unmatched = await db.fetchval(
        "SELECT count(*) FROM customers c WHERE c.onu_serial = ANY($1::text[]) "
        "AND NOT EXISTS (SELECT 1 FROM onus n WHERE n.serial = c.onu_serial)", [r["serial"] for _, r in rows])
    return ImportResult(created=created, updated=updated, unmatched=unmatched, errors=errors[:100])


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(customer_id: UUID, user: Admin, db: TenantDb) -> Response:
    if await db.execute("DELETE FROM customers WHERE id = $1", customer_id) == "DELETE 0":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cliente não encontrado")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ mapa

@router.get("/map", response_model=MapOut, summary="OLTs e clientes com coordenadas, com o estado de cada um")
async def network_map(user: User, db: TenantDb) -> MapOut:
    customers = [to_customer(r) for r in await db.fetch(
        f"SELECT * FROM ({CUSTOMER_SELECT}) x WHERE x.lat IS NOT NULL AND x.lon IS NOT NULL")]
    olts = []
    for o in await db.fetch(
            "SELECT o.id, o.name, o.lat, o.lon, o.reachable, "
            "(SELECT count(*) FROM onus n WHERE n.olt_id = o.id) AS onus_total, "
            "(SELECT count(*) FROM onus n WHERE n.olt_id = o.id AND n.online) AS onus_online, "
            "(SELECT count(*) FROM alarms a WHERE a.olt_id = o.id AND a.status <> 'cleared' AND a.parent_id IS NULL) "
            "AS open_alarms FROM olts o ORDER BY o.name"):
        lat, lon, located = o["lat"], o["lon"], o["lat"] is not None and o["lon"] is not None
        if not located:      # sem coordenada: centro dos clientes dela
            mine = [c for c in customers if c.olt_id == o["id"]]
            if mine:
                lat = sum(c.lat for c in mine) / len(mine)
                lon = sum(c.lon for c in mine) / len(mine)
        olts.append(MapOlt(id=o["id"], name=o["name"], lat=lat, lon=lon, located=located, reachable=o["reachable"],
                           onus_total=o["onus_total"], onus_online=o["onus_online"], open_alarms=o["open_alarms"]))
    return MapOut(olts=olts, customers=customers)


@router.get("/onus-at-risk", summary="ONUs com sinal piorando: devem passar do limite de alarme em até 7 dias")
async def onus_at_risk(user: User, db: TenantDb) -> list[dict]:
    return await trend.at_risk(db)
