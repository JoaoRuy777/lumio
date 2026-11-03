from lumio_sim.model import Network

from tests.conftest import small_config


def net():
    return Network.from_config(small_config([16101]))


def test_mesma_seed_gera_mesma_rede():
    a, b = net(), net()
    serials = lambda n: [u.serial for p in n.olt("olt-1").pons.values() for u in p.onus.values()]
    assert serials(a) == serials(b)
    assert len(serials(a)) == 16


def test_sinal_inicial_dentro_da_faixa_normal():
    for p in net().olt("olt-1").pons.values():
        for u in p.onus.values():
            assert -25 < u.rx < -8


def test_rompimento_de_fibra_derruba_a_porta_inteira():
    n = net()
    events = n.run("fiber_cut", olt="olt-1", pon="0/1/0")
    assert len(events) == 8
    assert all(not u.online for u in n.olt("olt-1").pon("0/1/0").onus.values())
    assert all(u.online for u in n.olt("olt-1").pon("0/1/1").onus.values())


def test_degradacao_cruza_as_faixas_e_gera_evento():
    n = net()
    n.run("degrade", olt="olt-1", pon="0/1/1", onu=3, rate_db_per_min=1.0, target_dbm=-30)
    events = []
    for _ in range(20):
        events += n.tick(minutes=1)
    onu = n.olt("olt-1").onu("0/1/1", 3)
    assert onu.rx < -28
    assert [e.kind for e in events] == ["onu_rx_low"]


def test_reset_volta_tudo_ao_normal():
    n = net()
    n.run("fiber_cut", olt="olt-1", pon="0/1/0")
    n.run("olt_down", olt="olt-1")
    n.run("reset")
    o = n.olt("olt-1")
    assert o.reachable
    assert all(u.online for p in o.pons.values() for u in p.onus.values())
