from lumio_collector.vendors.huawei import _power, _serial, pon_name
from lumio_sim.profiles.huawei import pon_ifindex


def test_ifindex_ida_e_volta():
    for slot in range(0, 18):
        for port in range(16):
            assert pon_name(pon_ifindex(0, slot, port)) == f"0/{slot}/{port}"


def test_potencia_em_centesimos_e_sem_leitura():
    assert _power(-2137) == -21.37
    assert _power(2147483647) is None


def test_serial_vendor_mais_hex():
    assert _serial(b"HWTC" + bytes.fromhex("85ED0324")) == "HWTC85ED0324"
