"""Visão geral do provedor: números da tela inicial do painel."""

from __future__ import annotations

from fastapi import APIRouter

from .. import trend
from ..deps import TenantDb, User
from ..schemas import Overview
from .alarms import fetch_alarms
from .olts import OLT_SELECT, collection_status

router = APIRouter(prefix="/overview", tags=["painel"])

RX_LOW_DBM = -27.0      # mesmo limite do worker (worker/lumio_worker/rules.py)


@router.get("", response_model=Overview)
async def overview(user: User, db: TenantDb) -> Overview:
    olts = {"total": 0, "ok": 0, "error": 0, "late": 0, "pending": 0, "disabled": 0}
    for row in await db.fetch(OLT_SELECT):
        olts["total"] += 1
        olts[collection_status(row)] += 1

    onus = await db.fetchrow(
        "SELECT count(*) AS total, count(*) FILTER (WHERE online) AS online, "
        "count(*) FILTER (WHERE online IS FALSE) AS offline, count(*) FILTER (WHERE online IS NULL) AS unknown, "
        "count(*) FILTER (WHERE online AND rx_dbm < $1) AS rx_low FROM onus", RX_LOW_DBM)

    alarms = {"critical": 0, "major": 0, "minor": 0, "warning": 0}
    for row in await db.fetch("SELECT severity, count(*) FROM alarms WHERE status <> 'cleared' "
                              "AND parent_id IS NULL GROUP BY severity"):
        alarms[row["severity"]] = row["count"]
    alarms["total"] = sum(alarms.values())

    recent = await fetch_alarms(db, status_="open", limit=8)
    return Overview(
        olts=olts,
        onus={k: onus[k] for k in ("total", "online", "offline", "unknown")},
        rx_low=onus["rx_low"],
        rx_trend=await db.fetchval(f"SELECT count(*) FROM ({trend.TREND_SQL}) t"),
        customers=await db.fetchval("SELECT count(*) FROM customers"),
        alarms=alarms,
        recent_alarms=recent.items,
    )
