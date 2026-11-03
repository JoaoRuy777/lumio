"""Regras de alarme: limites, severidades e chaves de deduplicação.

Funções puras, sem banco, para serem fáceis de testar e de citar no TCC.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

# Potência óptica (dBm). Histerese: abre abaixo de -27 e só fecha acima de -26,
# para um sinal oscilando na fronteira não abrir/fechar alarme a cada leitura.
RX_LOW_OPEN_DBM = -27.0
RX_LOW_CLEAR_DBM = -26.0

# CPU da OLT (%), também com histerese
CPU_HIGH_OPEN = 85.0
CPU_HIGH_CLEAR = 80.0

# Rompimento de fibra: todas as ONUs da PON offline, sendo que pelo menos
# FIBER_CUT_MIN_ONUS caíram dentro desta janela
FIBER_CUT_WINDOW_S = 5.0
FIBER_CUT_MIN_ONUS = 2
# O rompimento é encerrado quando ao menos esta fração da PON volta
FIBER_CUT_CLEAR_RATIO = 0.5

SEVERITY = {
    "pon_fiber_cut": "critical",
    "olt_unreachable": "critical",
    "olt_cpu_high": "major",
    "onu_offline": "minor",
    "onu_rx_low": "warning",
}


@dataclass(frozen=True)
class AlarmRef:
    """Identifica um alarme: o tipo e o objeto afetado (OLT, PON ou ONU)."""

    kind: str
    object_id: UUID

    @property
    def dedup_key(self) -> str:
        return f"{self.kind}:{self.object_id}"

    @property
    def severity(self) -> str:
        return SEVERITY[self.kind]


def rx_low_action(rx_dbm: float | None) -> str | None:
    """'open', 'clear' ou None (dentro da histerese ou sem leitura)."""
    if rx_dbm is None:
        return None
    if rx_dbm < RX_LOW_OPEN_DBM:
        return "open"
    if rx_dbm >= RX_LOW_CLEAR_DBM:
        return "clear"
    return None


def cpu_high_action(cpu: float | None) -> str | None:
    if cpu is None:
        return None
    if cpu >= CPU_HIGH_OPEN:
        return "open"
    if cpu < CPU_HIGH_CLEAR:
        return "clear"
    return None


def is_fiber_cut(total: int, offline: int, recent_offline: int) -> bool:
    """Todas as ONUs conhecidas da PON caíram, e várias delas juntas.

    `recent_offline` conta as que ficaram offline dentro de FIBER_CUT_WINDOW_S.
    ONUs que já estavam offline antes (cliente desligou o equipamento) não
    impedem a detecção, mas a queda tem de ser coletiva.
    """
    return total >= FIBER_CUT_MIN_ONUS and offline == total and recent_offline >= FIBER_CUT_MIN_ONUS


def fiber_cut_recovered(total: int, online: int) -> bool:
    return total > 0 and online / total >= FIBER_CUT_CLEAR_RATIO
