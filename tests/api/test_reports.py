"""Relatórios (sprint 5): números conferíveis à mão.

Período: 04/11/2026 das 10:00 às 12:00 (UTC), 2 h = 120 min. OLT com 4 ONUs.
- ONU 0 offline 10:30-11:00 -> 30 min
- ONU 1 offline 09:00-10:15 -> 15 min dentro do período (começou antes)
- ONU 2 offline desde 11:45, ainda aberta -> 15 min (cortado no fim)
- OLT inacessível 11:00-11:12 -> 12 min
Disponibilidade da rede = 1 - 60 / (4 x 120) = 87,5 %. Da gerência = 1 - 12/120 = 90 %.
Alarmes que começaram no período: ONU 0, ONU 2 e OLT inacessível (3); MTTR = (30 + 12) / 2 = 21 min.
"""

import csv
import io
from datetime import datetime

import pytest

from .conftest import needs_db, signup

pytestmark = needs_db

FROM, TO = "2026-11-04T10:00:00Z", "2026-11-04T12:00:00Z"


@pytest.fixture
async def seeded(client, pool):
    h = await signup(client, company="Provedor Relatório")
    tid = await pool.fetchval("SELECT id FROM tenants")
    olt = await pool.fetchval("INSERT INTO olts (tenant_id, name, host) VALUES ($1, 'Centro', 'x') RETURNING id", tid)
    pon = await pool.fetchval("INSERT INTO pon_ports (tenant_id, olt_id, name) VALUES ($1, $2, '0/1/0') RETURNING id", tid, olt)
    onus = [await pool.fetchval("INSERT INTO onus (tenant_id, olt_id, pon_id, onu_index, serial, online) "
                                "VALUES ($1, $2, $3, $4, $5, true) RETURNING id", tid, olt, pon, i, f"HWTC0000000{i}")
            for i in range(4)]

    async def alarm(kind, severity, start, end, onu=None):
        start = datetime.fromisoformat(start)
        end = end and datetime.fromisoformat(end)
        await pool.execute(
            "INSERT INTO alarms (tenant_id, olt_id, pon_id, onu_id, kind, severity, dedup_key, source, status, "
            "event_ts, first_seen_at, last_seen_at, cleared_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, gen_random_uuid()::text, 'trap', $7, $8, $8, $8, $9)",
            tid, olt, pon if onu is not None else None, onu, kind, severity,
            "cleared" if end else "active", start, end)

    await alarm("onu_offline", "minor", "2026-11-04T10:30:00Z", "2026-11-04T11:00:00Z", onus[0])
    await alarm("onu_offline", "minor", "2026-11-04T09:00:00Z", "2026-11-04T10:15:00Z", onus[1])
    await alarm("onu_offline", "minor", "2026-11-04T11:45:00Z", None, onus[2])
    await alarm("olt_unreachable", "critical", "2026-11-04T11:00:00Z", "2026-11-04T11:12:00Z")
    await alarm("onu_offline", "minor", "2026-11-03T08:00:00Z", "2026-11-03T09:00:00Z", onus[3])   # fora do período
    return h


async def get(client, h, path, **params):
    return await client.get(f"/api/reports/{path}", headers=h, params={"from": FROM, "to": TO, **params})


async def test_disponibilidade(client, seeded):
    rep = (await get(client, seeded, "availability")).json()
    [olt] = rep["olts"]
    assert olt == {"olt": "Centro", "onus": 4, "availability_pct": 87.5, "onu_downtime_min": 60.0, "onu_outages": 3,
                   "fiber_cuts": 0, "olt_management_pct": 90.0, "olt_unreachable_min": 12.0}
    assert rep["overall_availability_pct"] == 87.5
    assert [(w["onu"], w["downtime_min"]) for w in rep["worst_onus"]] == [(0, 30.0), (1, 15.0), (2, 15.0)]
    assert rep["worst_onus"][0]["availability_pct"] == 75.0


async def test_alarmes_e_mttr(client, seeded):
    rep = (await get(client, seeded, "alarms")).json()
    assert (rep["total"], rep["open"], rep["mttr_min"]) == (3, 1, 21.0)
    assert rep["by_kind"] == {"onu_offline": 2, "olt_unreachable": 1}
    assert [i["duration_min"] for i in rep["items"]] == [30.0, 12.0, None]


async def test_csv_abre_no_excel_brasileiro(client, seeded):
    resp = await get(client, seeded, "availability", format="csv")
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="lumio-disponibilidade-2026-11-04_2026-11-04.csv"' in resp.headers["content-disposition"]
    assert resp.content.startswith(b"\xef\xbb\xbf")                       # BOM UTF-8
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][2] == "Disponibilidade da rede (%)"
    assert rows[1][:3] == ["Centro", "4", "87,500"]                       # vírgula decimal

    alarms = list(csv.reader(io.StringIO((await get(client, seeded, "alarms", format="csv")).content.decode("utf-8-sig")),
                             delimiter=";"))
    assert len(alarms) == 4
    assert alarms[1][:5] == ["04/11/2026 07:30:00", "04/11/2026 08:00:00", "30,0", "ONU offline", "Menor"]  # horário de Brasília


async def test_pdf(client, seeded):
    for path in ("availability", "alarms"):
        resp = await get(client, seeded, path, format="pdf")
        assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF-") and len(resp.content) > 1500
        assert ".pdf" in resp.headers["content-disposition"]


@pytest.mark.parametrize("params", [
    {"from": TO, "to": FROM},                                              # invertido
    {"from": "2024-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"},       # mais de 366 dias
    {"from": "2026-11-04T10:00:00", "to": "2026-11-04T12:00:00"},         # sem fuso
    {"format": "xlsx"},
])
async def test_validacao_do_periodo(client, seeded, params):
    resp = await client.get("/api/reports/availability", headers=seeded, params=params)
    assert resp.status_code == 422


async def test_padrao_ultimos_7_dias(client, seeded):
    from datetime import timedelta

    rep = (await client.get("/api/reports/alarms", headers=seeded)).json()
    start, end = (datetime.fromisoformat(rep["period"][k]) for k in ("from", "to"))
    assert end - start == timedelta(days=7)


def test_disponibilidade_truncada_nunca_mostra_100_com_falha():
    from lumio_api.reports import pct

    assert pct(0, 1000) == 100.0
    assert pct(4.8 * 60, 128 * 7 * 86400) == 99.999        # arredondando daria 100,000
    assert pct(60 * 60, 4 * 120 * 60) == 87.5               # sem erro de ponto flutuante (87,499...)
