"""Simulador e coletor conversando por SNMP de verdade (UDP local)."""

import time

import pytest

from lumio_collector.poller import probe
from lumio_collector.snmp import SnmpError, Target


async def test_testar_conexao_identifica_a_olt(lab):
    olt = lab.network.olt("olt-1")
    info = await probe(lab.client, Target("127.0.0.1", olt.port))
    assert info == {
        "ok": True, "vendor": "huawei", "model": "MA5800-X7", "sys_name": "olt-1",
        "pon_ports": ["0/1/0", "0/1/1"], "onus": 16,
    }


async def test_community_errada_nao_responde(lab):
    olt = lab.network.olt("olt-1")
    with pytest.raises(SnmpError):
        await lab.client.get(Target("127.0.0.1", olt.port, "errada", timeout=0.3, retries=0), (1, 3, 6, 1, 2, 1, 1, 5, 0))


async def test_polling_le_estado_e_potencia(lab):
    w = lab.workers[0]
    await w.run_once(w.collect_status)
    await w.run_once(w.collect_optical)
    status = lab.sink.of("onu_status", olt="olt-1")[0]["onus"]
    optical = lab.sink.of("onu_optical", olt="olt-1")[0]["onus"]
    assert len(status) == len(optical) == 16
    real = {(p.name, u.onu_id): u for p in lab.network.olt("olt-1").pons.values() for u in p.onus.values()}
    for r in optical:
        assert r["rx_dbm"] == pytest.approx(real[(r["pon"], r["onu"])].rx, abs=0.01)
    assert {s["serial"] for s in status} == {u.serial for u in real.values()}


async def test_rompimento_de_fibra_chega_por_trap_em_menos_de_1s(lab):
    t0 = time.perf_counter()
    await lab.scenario("fiber_cut", olt="olt-2", pon="0/1/1")
    ok = await lab.wait_for(lambda: len(lab.sink.of("event", kind="onu_offline")) == 8)
    latency = time.perf_counter() - t0
    assert ok, lab.sink.records
    events = lab.sink.of("event", kind="onu_offline")
    assert {e["olt"] for e in events} == {"olt-2"}       # mesmo IP, separado pelo sysName
    assert {e["pon"] for e in events} == {"0/1/1"}
    assert all(e["source"] == "trap" for e in events)
    assert latency < 1.0
    print(f"\nlatência trap -> evento: {latency * 1000:.0f} ms")


async def test_sinal_degradado_gera_trap_com_a_potencia(lab):
    await lab.scenario("degrade", olt="olt-1", pon="0/1/0", onu=2, rate_db_per_min=2.0, target_dbm=-30)
    for _ in range(10):
        await lab.traps.send(lab.network.tick(minutes=1))
    assert await lab.wait_for(lambda: lab.sink.of("event", kind="onu_rx_low"))
    ev = lab.sink.of("event", kind="onu_rx_low")[0]
    assert (ev["olt"], ev["pon"], ev["onu"]) == ("olt-1", "0/1/0", 2)
    assert ev["rx_dbm"] < -27


async def test_olt_fora_do_ar_e_volta(lab):
    w = lab.workers[0]
    await lab.scenario("olt_down", olt="olt-1")
    await w.run_once(w.collect_status)
    await lab.scenario("reset", olt="olt-1")
    await w.run_once(w.collect_status)
    kinds = [e["kind"] for e in lab.sink.of("event", olt="olt-1") if e["source"] == "poll"]
    assert kinds == ["olt_unreachable", "olt_reachable"]
