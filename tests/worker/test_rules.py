"""Regras puras (sem banco)."""

import uuid

import pytest

from lumio_worker import rules
from lumio_worker.rules import AlarmRef


@pytest.mark.parametrize("rx, expected", [
    (None, None), (-20.0, "clear"), (-26.0, "clear"), (-26.5, None), (-27.0, None), (-27.01, "open"), (-35.0, "open"),
])
def test_histerese_do_sinal(rx, expected):
    assert rules.rx_low_action(rx) == expected


@pytest.mark.parametrize("cpu, expected", [(None, None), (20, "clear"), (82, None), (85, "open"), (99, "open")])
def test_histerese_da_cpu(cpu, expected):
    assert rules.cpu_high_action(cpu) == expected


def test_rompimento_exige_queda_coletiva():
    assert rules.is_fiber_cut(total=8, offline=8, recent_offline=8)
    assert rules.is_fiber_cut(total=8, offline=8, recent_offline=3)      # 5 já estavam fora
    assert not rules.is_fiber_cut(total=8, offline=7, recent_offline=7)  # uma ainda online
    assert not rules.is_fiber_cut(total=8, offline=8, recent_offline=1)  # caíram uma a uma
    assert not rules.is_fiber_cut(total=1, offline=1, recent_offline=1)  # PON com uma ONU só


def test_chave_de_deduplicacao_por_objeto():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert AlarmRef("onu_offline", a).dedup_key == AlarmRef("onu_offline", a).dedup_key
    assert AlarmRef("onu_offline", a).dedup_key != AlarmRef("onu_offline", b).dedup_key
    assert AlarmRef("onu_offline", a).dedup_key != AlarmRef("onu_rx_low", a).dedup_key
    assert AlarmRef("pon_fiber_cut", a).severity == "critical"
