"""Formato único que todos os drivers de fabricante devolvem.

Daqui para frente (worker, banco, tela), ninguém sabe se a OLT é Huawei ou
ZTE: só enxerga estes objetos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..snmp import Oid, SnmpClient, Target


@dataclass
class OnuStatus:
    pon: str            # "0/1/3"
    onu: int
    serial: str
    online: bool


@dataclass
class OnuOptical:
    pon: str
    onu: int
    rx_dbm: float | None     # None quando a ONU está offline (sem leitura)
    tx_dbm: float | None


@dataclass
class OltHealth:
    cpu: float | None
    temperature: float | None
    uptime_s: float | None


@dataclass
class OltInfo:
    vendor: str
    model: str
    sys_name: str
    pon_ports: list[str] = field(default_factory=list)
    onus: int = 0


@dataclass
class TrapEvent:
    kind: str                # onu_offline, onu_online, onu_rx_low, olt_cpu_high
    sys_name: str | None = None
    pon: str | None = None
    onu: int | None = None
    serial: str | None = None
    rx_dbm: float | None = None
    cpu: float | None = None


class Driver(Protocol):
    name: str

    def matches(self, sys_object_id: Oid) -> bool: ...
    async def info(self, client: SnmpClient, t: Target) -> OltInfo: ...
    async def onu_status(self, client: SnmpClient, t: Target) -> list[OnuStatus]: ...
    async def onu_optical(self, client: SnmpClient, t: Target) -> list[OnuOptical]: ...
    async def health(self, client: SnmpClient, t: Target) -> OltHealth: ...
    def parse_trap(self, trap_oid: Oid, binds: dict[Oid, object]) -> TrapEvent | None: ...
