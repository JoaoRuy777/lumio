"""Sinal piorando: tendência da potência recebida (manutenção preventiva).

Para cada ONU online, uma regressão linear da potência (rx_dbm) contra o tempo
nas últimas WINDOW_H horas dá a inclinação em dB por dia. A ONU entra na lista
quando o sinal ainda está acima do limite de alarme, mas cai rápido o bastante
para cruzá-lo em até HORIZON_DAYS dias. Ou seja: avisa antes de o cliente cair.

    dias até o limite = (rx_atual - limite) / |inclinação|

Precisa de pelo menos MIN_POINTS leituras (a coleta de potência é a cada 5 min
por padrão: 6 leituras = meia hora de histórico).
"""

from __future__ import annotations

import asyncpg

RX_LIMIT_DBM = -27.0         # mesmo limite do alarme de sinal baixo (worker)
WINDOW_H = 24
MIN_POINTS = 6
MIN_SLOPE_DB_DAY = -0.5      # quedas mais lentas que isso são ruído/variação normal
HORIZON_DAYS = 7

TREND_SQL = f"""
    WITH t AS (
        SELECT r.onu_id,
               regr_slope(r.rx_dbm, extract(epoch FROM r.ts)) * 86400 AS slope_db_day,
               count(*) AS points
        FROM optical_readings r
        WHERE r.ts > now() - interval '{WINDOW_H} hours' AND r.rx_dbm IS NOT NULL
        GROUP BY r.onu_id
        HAVING count(*) >= {MIN_POINTS}
    )
    SELECT n.id AS onu_id, n.serial, n.onu_index, n.rx_dbm, o.id AS olt_id, o.name AS olt_name, p.name AS pon,
           t.slope_db_day, t.points,
           (n.rx_dbm - ({RX_LIMIT_DBM})) / (-t.slope_db_day) AS days_to_limit
    FROM t
    JOIN onus n ON n.id = t.onu_id
    JOIN olts o ON o.id = n.olt_id
    JOIN pon_ports p ON p.id = n.pon_id
    WHERE n.online AND n.rx_dbm > {RX_LIMIT_DBM} AND t.slope_db_day <= {MIN_SLOPE_DB_DAY}
      AND (n.rx_dbm - ({RX_LIMIT_DBM})) / (-t.slope_db_day) <= {HORIZON_DAYS}
"""


async def at_risk(db: asyncpg.Connection) -> list[dict]:
    """ONUs com sinal piorando, as mais urgentes primeiro."""
    rows = await db.fetch(TREND_SQL + " ORDER BY days_to_limit")
    return [{**dict(r), "slope_db_day": round(r["slope_db_day"], 2), "days_to_limit": round(r["days_to_limit"], 2),
             "rx_dbm": round(r["rx_dbm"], 2)} for r in rows]
