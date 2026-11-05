"""Visão geral do provedor: números da tela inicial do painel."""

from __future__ import annotations

from fastapi import APIRouter

from .. import trend
from ..deps import TenantDb, User
from ..schemas import Overview, OverviewHistory
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
        customers_offline=await db.fetchval(
            "SELECT count(*) FROM customers c JOIN onus n ON n.tenant_id = c.tenant_id AND n.serial = c.onu_serial "
            "WHERE n.online IS FALSE"),
        alarms=alarms,
        recent_alarms=recent.items,
    )


# Histórico das últimas 24 h, hora a hora, para os mini-gráficos da visão geral.
# Não há tabela de "estado a cada hora": tudo sai da linha de vida dos alarmes
# (aberto em created_at, encerrado em cleared_at). ONUs offline = alarmes
# onu_offline (os de dentro de um rompimento também) ativos naquele instante.
HISTORY_SQL = """
    WITH h AS (
        SELECT t, least(t + interval '1 hour', now()) AS p
        FROM generate_series(date_trunc('hour', now()) - interval '23 hours', date_trunc('hour', now()),
                             interval '1 hour') AS t
    )
    SELECT h.t,
           (SELECT count(*) FILTER (WHERE a.severity = 'critical') FROM alarms a
             WHERE a.parent_id IS NULL AND a.created_at >= h.t AND a.created_at < h.t + interval '1 hour') AS critical,
           (SELECT count(*) FILTER (WHERE a.severity = 'major') FROM alarms a
             WHERE a.parent_id IS NULL AND a.created_at >= h.t AND a.created_at < h.t + interval '1 hour') AS major,
           (SELECT count(*) FILTER (WHERE a.severity IN ('minor', 'warning')) FROM alarms a
             WHERE a.parent_id IS NULL AND a.created_at >= h.t AND a.created_at < h.t + interval '1 hour') AS other,
           (SELECT count(*) FROM alarms a
             WHERE a.parent_id IS NULL AND a.created_at <= h.p AND (a.cleared_at IS NULL OR a.cleared_at > h.p)) AS open,
           (SELECT count(DISTINCT a.onu_id) FROM alarms a
             WHERE a.kind = 'onu_offline' AND a.created_at <= h.p
               AND (a.cleared_at IS NULL OR a.cleared_at > h.p)) AS onus_offline
    FROM h ORDER BY h.t
"""


@router.get("/history", response_model=OverviewHistory)
async def overview_history(user: User, db: TenantDb) -> OverviewHistory:
    """Últimas 24 h, uma linha por hora: alarmes abertos naquela hora (por severidade),
    alarmes em aberto e ONUs offline ao fim de cada hora."""
    return OverviewHistory(hours=[dict(r) for r in await db.fetch(HISTORY_SQL)])
