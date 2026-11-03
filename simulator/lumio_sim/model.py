"""Modelo em memória da rede simulada: OLTs, portas PON e ONUs.

O modelo não sabe nada de SNMP. Ele só guarda o estado da rede, faz o sinal
variar a cada tick e aplica os cenários de falha. Os perfis de fabricante
(profiles/) traduzem esse estado para as OIDs de cada equipamento.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

# Faixa típica de recepção de uma ONU saudável em GPON (ITU-T G.984)
RX_BASE_MIN = -24.0
RX_BASE_MAX = -18.0
RX_NOISE = 0.3          # variação máxima por tick, em dB
RX_PULL = 0.2           # quanto o sinal "volta" para a base a cada tick
TX_NOMINAL = 2.2


@dataclass
class Event:
    """Algo que aconteceu na rede e que vira trap para o coletor."""

    kind: str           # onu_offline, onu_online, onu_degraded, olt_cpu_high...
    olt: str
    pon: str | None = None
    onu: int | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class Onu:
    onu_id: int
    serial: str
    base_rx: float
    rx: float
    tx: float = TX_NOMINAL
    online: bool = True
    down_cause: str | None = None       # "los", "dying-gasp"
    degrade_rate: float = 0.0           # dB por minuto, > 0 quando degradando
    degrade_target: float = 0.0

    def tick(self, rng: random.Random, minutes: float) -> None:
        if not self.online:
            return
        if self.degrade_rate:
            self.base_rx = max(self.degrade_target, self.base_rx - self.degrade_rate * minutes)
        noise = rng.uniform(-RX_NOISE, RX_NOISE)
        self.rx = round(self.rx + (self.base_rx - self.rx) * RX_PULL + noise, 2)
        self.tx = round(TX_NOMINAL + rng.uniform(-0.1, 0.1), 2)


@dataclass
class PonPort:
    frame: int
    slot: int
    port: int
    onus: dict[int, Onu] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.frame}/{self.slot}/{self.port}"


@dataclass
class Olt:
    name: str
    vendor: str
    model: str
    host: str
    port: int
    community: str
    pons: dict[str, PonPort] = field(default_factory=dict)
    reachable: bool = True
    cpu: float = 20.0
    cpu_target: float = 20.0
    temperature: float = 42.0
    started_at: float = field(default_factory=time.monotonic)

    def pon(self, name: str) -> PonPort:
        try:
            return self.pons[name]
        except KeyError:
            raise LookupError(f"porta PON {name} não existe na {self.name}") from None

    def onu(self, pon: str, onu_id: int) -> Onu:
        try:
            return self.pon(pon).onus[onu_id]
        except KeyError:
            raise LookupError(f"ONU {onu_id} não existe na porta {pon} da {self.name}") from None

    def tick(self, rng: random.Random, minutes: float) -> None:
        self.cpu = round(min(100.0, max(1.0, self.cpu + (self.cpu_target - self.cpu) * 0.5 + rng.uniform(-2, 2))), 1)
        self.temperature = round(42.0 + (self.cpu - 20.0) * 0.15 + rng.uniform(-0.5, 0.5), 1)
        for pon in self.pons.values():
            for onu in pon.onus.values():
                onu.tick(rng, minutes)


SCENARIOS = ("onu_down", "onu_up", "degrade", "fiber_cut", "olt_down", "overload", "reset")


class Network:
    """A rede inteira. Toda mudança de estado passa por aqui."""

    def __init__(self, olts: list[Olt], seed: int, thresholds: dict | None = None):
        self.olts = {o.name: o for o in olts}
        self.rng = random.Random(seed)
        # Limiares usados só para gerar traps de sinal degradado; as faixas
        # de alarme de verdade ficam na Lumio, não no equipamento.
        self.thresholds = {"rx_low": -27.0, **(thresholds or {})}
        self._degraded: set[tuple[str, str, int]] = set()
        # Sobe a cada mudança; o agente SNMP usa para saber quando refazer a tabela de OIDs.
        self.version = 0

    @classmethod
    def from_config(cls, cfg: dict) -> "Network":
        seed = int(cfg.get("seed", 42))
        rng = random.Random(seed)
        olts = []
        base_port = int(cfg.get("base_port", 16101))
        for i, o in enumerate(cfg["olts"]):
            olt = Olt(
                name=o["name"],
                vendor=o.get("vendor", "huawei"),
                model=o.get("model", "MA5800-X7"),
                host=o.get("host", "0.0.0.0"),
                port=int(o.get("port", base_port + i)),
                community=o.get("community", "public"),
            )
            frame = int(o.get("frame", 0))
            for slot in o.get("slots", [1]):
                for p in range(int(o.get("ports_per_slot", 4))):
                    pon = PonPort(frame, int(slot), p)
                    for onu_id in range(int(o.get("onus_per_port", 16))):
                        base = round(rng.uniform(RX_BASE_MIN, RX_BASE_MAX), 2)
                        serial = "HWTC" + "".join(rng.choice("0123456789ABCDEF") for _ in range(8))
                        pon.onus[onu_id] = Onu(onu_id, serial, base, base)
                    olt.pons[pon.name] = pon
            olts.append(olt)
        return cls(olts, seed + 1, cfg.get("thresholds"))

    def olt(self, name: str) -> Olt:
        try:
            return self.olts[name]
        except KeyError:
            raise LookupError(f"OLT {name} não existe") from None

    # ------------------------------------------------------------------ tempo

    def tick(self, minutes: float) -> list[Event]:
        """Avança o relógio da simulação e devolve os eventos gerados."""
        self.version += 1
        events: list[Event] = []
        for olt in self.olts.values():
            if not olt.reachable:
                continue
            olt.tick(self.rng, minutes)
            for pon in olt.pons.values():
                for onu in pon.onus.values():
                    key = (olt.name, pon.name, onu.onu_id)
                    low = onu.online and onu.rx < self.thresholds["rx_low"]
                    if low and key not in self._degraded:
                        self._degraded.add(key)
                        events.append(Event("onu_rx_low", olt.name, pon.name, onu.onu_id, {"rx_dbm": onu.rx}))
                    elif not low and key in self._degraded:
                        self._degraded.discard(key)
        return events

    # -------------------------------------------------------------- cenários

    def run(self, scenario: str, **params) -> list[Event]:
        """Executa um cenário pelo nome (é o que a API HTTP chama)."""
        handler = getattr(self, scenario, None) if scenario in SCENARIOS else None
        if handler is None:
            raise LookupError(f"cenário desconhecido: {scenario}")
        events = handler(**params)
        self.version += 1
        return events

    def onu_down(self, olt: str, pon: str, onu: int, cause: str = "los") -> list[Event]:
        o = self.olt(olt).onu(pon, onu)
        if not o.online:
            return []
        o.online, o.down_cause = False, cause
        return [Event("onu_offline", olt, pon, onu, {"cause": cause})]

    def onu_up(self, olt: str, pon: str, onu: int) -> list[Event]:
        o = self.olt(olt).onu(pon, onu)
        if o.online:
            return []
        o.online, o.down_cause = True, None
        o.rx = o.base_rx
        return [Event("onu_online", olt, pon, onu)]

    def degrade(self, olt: str, pon: str, onu: int, rate_db_per_min: float = 0.5, target_dbm: float = -30.0) -> list[Event]:
        o = self.olt(olt).onu(pon, onu)
        o.degrade_rate, o.degrade_target = rate_db_per_min, target_dbm
        return []

    def fiber_cut(self, olt: str, pon: str) -> list[Event]:
        events = []
        for onu in self.olt(olt).pon(pon).onus:
            events += self.onu_down(olt, pon, onu, cause="los")
        return events

    def olt_down(self, olt: str) -> list[Event]:
        # OLT fora do ar não manda trap: a Lumio tem que perceber pela falta de resposta.
        self.olt(olt).reachable = False
        return []

    def overload(self, olt: str, cpu: float = 95.0) -> list[Event]:
        o = self.olt(olt)
        o.cpu_target = o.cpu = cpu
        return [Event("olt_cpu_high", olt, detail={"cpu": cpu})]

    def reset(self, olt: str | None = None) -> list[Event]:
        events: list[Event] = []
        targets = [self.olt(olt)] if olt else list(self.olts.values())
        for o in targets:
            o.reachable = True
            o.cpu_target = 20.0
            for pon in o.pons.values():
                for onu in pon.onus.values():
                    if onu.degrade_rate:
                        onu.degrade_rate = 0.0
                        onu.base_rx = round(self.rng.uniform(RX_BASE_MIN, RX_BASE_MAX), 2)
                        onu.rx = onu.base_rx
                    events += self.onu_up(o.name, pon.name, onu.onu_id)
        return events
