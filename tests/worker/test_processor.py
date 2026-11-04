"""Regras de alarme aplicadas pelo worker, gravando num Postgres de verdade."""

from datetime import datetime, timedelta, timezone

import pytest

from .conftest import needs_db, rec

pytestmark = needs_db


def onus(pon="0/1/0", n=8, online=True):
    return [{"pon": pon, "onu": i, "serial": f"HWTC{pon[-1]}{i:07X}", "online": online} for i in range(n)]


async def alarms(pool, **where):
    sql = "SELECT * FROM alarms"
    if where:
        sql += " WHERE " + " AND ".join(f"{k} = ${i}" for i, k in enumerate(where, 1))
    return await pool.fetch(sql + " ORDER BY created_at", *where.values())


async def test_onu_offline_por_trap_abre_deduplica_e_encerra(processor, pool):
    await processor.handle(rec("onu_status", onus=onus()))
    trap = dict(kind="onu_offline", source="trap", pon="0/1/0", onu=3, serial="HWTC00003")
    await processor.handle(rec("event", **trap))
    await processor.handle(rec("event", **trap))           # trap repetida

    [a] = await alarms(pool, kind="onu_offline")
    assert (a["status"], a["severity"], a["source"], a["occurrences"]) == ("active", "minor", "trap", 2)
    assert a["onu_id"] is not None and a["latency_ms"] is not None and a["latency_ms"] >= 0

    await processor.handle(rec("event", kind="onu_online", source="trap", pon="0/1/0", onu=3))
    [a] = await alarms(pool, kind="onu_offline")
    assert a["status"] == "cleared" and a["cleared_at"] is not None


async def test_onu_offline_detectada_so_pelo_polling(processor, pool):
    await processor.handle(rec("onu_status", onus=onus()))
    estado = onus()
    estado[5]["online"] = False
    await processor.handle(rec("onu_status", onus=estado))
    [a] = await alarms(pool, kind="onu_offline")
    assert a["source"] == "poll"
    # leituras seguintes iguais não geram alarme novo nem ocorrência
    await processor.handle(rec("onu_status", onus=estado))
    [a] = await alarms(pool, kind="onu_offline")
    assert a["occurrences"] == 1


async def test_rompimento_de_fibra_agrupa_as_onus(processor, pool):
    await processor.handle(rec("onu_status", onus=onus("0/1/0") + onus("0/1/1")))
    for i in range(8):
        await processor.handle(rec("event", kind="onu_offline", source="trap", pon="0/1/1", onu=i))

    [cut] = await alarms(pool, kind="pon_fiber_cut")
    assert cut["severity"] == "critical" and cut["status"] == "active"
    filhos = await alarms(pool, kind="onu_offline")
    assert len(filhos) == 8
    assert all(f["parent_id"] == cut["id"] for f in filhos)

    # metade volta: o rompimento é encerrado; as ONUs que faltam seguem com alarme
    for i in range(4):
        await processor.handle(rec("event", kind="onu_online", source="trap", pon="0/1/1", onu=i))
    [cut] = await alarms(pool, kind="pon_fiber_cut")
    assert cut["status"] == "cleared"
    ativos = [f for f in await alarms(pool, kind="onu_offline") if f["status"] == "active"]
    assert len(ativos) == 4


async def test_onus_caindo_uma_a_uma_nao_e_rompimento(processor, pool):
    await processor.handle(rec("onu_status", onus=onus(n=4)))
    t = datetime.now(timezone.utc)
    for i in range(4):
        await processor.handle(rec("event", ts=t + timedelta(minutes=i), kind="onu_offline", source="trap",
                                   pon="0/1/0", onu=i))
    assert await alarms(pool, kind="pon_fiber_cut") == []
    assert len(await alarms(pool, kind="onu_offline")) == 4


async def test_sinal_baixo_com_histerese_e_leituras_guardadas(processor, pool):
    def optical(rx):
        return rec("onu_optical", onus=[{"pon": "0/1/0", "onu": 2, "rx_dbm": rx, "tx_dbm": 2.2},
                                        {"pon": "0/1/0", "onu": 3, "rx_dbm": None, "tx_dbm": None}])

    await processor.handle(optical(-28.1))
    [a] = await alarms(pool, kind="onu_rx_low")
    assert a["status"] == "active" and a["details"] == '{"rx_dbm": -28.1}'
    await processor.handle(optical(-26.5))                 # dentro da histerese: continua aberto
    assert (await alarms(pool, kind="onu_rx_low"))[0]["status"] == "active"
    await processor.handle(optical(-24.0))
    assert (await alarms(pool, kind="onu_rx_low"))[0]["status"] == "cleared"

    assert await pool.fetchval("SELECT count(*) FROM optical_readings") == 3   # ONU offline não grava
    assert await pool.fetchval("SELECT rx_dbm FROM onus WHERE onu_index = 2") == pytest.approx(-24.0)


async def test_trap_de_sinal_baixo_abre_alarme(processor, pool):
    await processor.handle(rec("event", kind="onu_rx_low", source="trap", pon="0/1/0", onu=2, rx_dbm=-27.4))
    [a] = await alarms(pool, kind="onu_rx_low")
    assert a["source"] == "trap"


async def test_olt_inacessivel_e_volta(processor, pool):
    await processor.handle(rec("event", kind="olt_unreachable", source="poll", error="timeout"))
    [a] = await alarms(pool, kind="olt_unreachable")
    assert a["severity"] == "critical"
    assert await pool.fetchval("SELECT reachable FROM olts") is False
    await processor.handle(rec("event", kind="olt_reachable", source="poll"))
    assert (await alarms(pool, kind="olt_unreachable"))[0]["status"] == "cleared"
    assert await pool.fetchval("SELECT reachable FROM olts") is True


async def test_cpu_alta_por_trap_e_por_polling(processor, pool):
    def health(cpu):
        return rec("olt_health", cpu=cpu, temperature=42.0, uptime_s=100.0)

    await processor.handle(rec("event", kind="olt_cpu_high", source="trap", cpu=93.0))
    await processor.handle(health(91))
    [a] = await alarms(pool, kind="olt_cpu_high")
    assert (a["severity"], a["occurrences"]) == ("major", 2)
    await processor.handle(health(82))                     # histerese
    assert (await alarms(pool, kind="olt_cpu_high"))[0]["status"] == "active"
    await processor.handle(health(30))
    assert (await alarms(pool, kind="olt_cpu_high"))[0]["status"] == "cleared"
    assert await pool.fetchval("SELECT count(*) FROM olt_health_readings") == 3


async def test_alarme_reaberto_depois_de_encerrado_e_um_novo(processor, pool):
    off = dict(kind="onu_offline", source="trap", pon="0/1/0", onu=1)
    on = dict(kind="onu_online", source="trap", pon="0/1/0", onu=1)
    for ev in (off, on, off):
        await processor.handle(rec("event", **ev))
    rows = await alarms(pool, kind="onu_offline")
    assert [r["status"] for r in rows] == ["cleared", "active"]


async def test_rls_isola_os_tenants(processor, pool):
    """Prévia da sprint 3: o papel da API só enxerga o próprio tenant."""
    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))
    outro = await pool.fetchval("INSERT INTO tenants (name, slug) VALUES ('outro', 'outro') RETURNING id")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL ROLE lumio_app")
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(outro))
        assert await conn.fetchval("SELECT count(*) FROM alarms") == 0
        assert await conn.fetchval("SELECT count(*) FROM olts") == 0
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(processor.tenant_id))
        assert await conn.fetchval("SELECT count(*) FROM alarms") == 1


async def test_rompimento_detectado_so_pelo_polling(processor, pool):
    """Sprint 6 (UPDATE em lote): as 8 ONUs caem no mesmo registro de estado."""
    await processor.handle(rec("onu_status", onus=onus("0/1/0") + onus("0/1/1")))
    estado = onus("0/1/0") + onus("0/1/1", online=False)
    await processor.handle(rec("onu_status", onus=estado))
    [cut] = await alarms(pool, kind="pon_fiber_cut")
    assert cut["source"] == "poll"
    filhos = await alarms(pool, kind="onu_offline")
    assert len(filhos) == 8 and all(f["parent_id"] == cut["id"] for f in filhos)
    # mesmo registro de novo: nada muda (sem transição)
    await processor.handle(rec("onu_status", onus=estado))
    assert len(await alarms(pool)) == 9
    assert await pool.fetchval("SELECT count(DISTINCT serial) FROM onus") == 16


async def test_varios_sinais_normalizam_na_mesma_leitura(processor, pool):
    def optical(rx):
        return rec("onu_optical", onus=[{"pon": "0/1/0", "onu": i, "rx_dbm": rx, "tx_dbm": 2.2} for i in range(5)])

    await processor.handle(optical(-28.0))
    assert len(await alarms(pool, kind="onu_rx_low", status="active")) == 5
    await processor.handle(optical(-22.0))
    assert len(await alarms(pool, kind="onu_rx_low", status="cleared")) == 5
    assert await pool.fetchval("SELECT count(*) FROM optical_readings") == 10
    assert await pool.fetchval("SELECT count(*) FROM onus WHERE rx_dbm = -22.0") == 5
