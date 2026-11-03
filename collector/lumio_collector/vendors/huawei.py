"""Driver Huawei (MA5600T/MA5800) via HUAWEI-XPON-MIB.

OIDs conferidas com o simulador. Confirmar com um snmpwalk de OLT real
antes de usar em produção, principalmente as de trap (TRAP_*), que hoje
são as de laboratório do simulador.
"""

from __future__ import annotations

from ..snmp import Oid, SnmpClient, Target
from .base import OltHealth, OltInfo, OnuOptical, OnuStatus, TrapEvent

SYS_DESCR = (1, 3, 6, 1, 2, 1, 1, 1, 0)
SYS_UPTIME = (1, 3, 6, 1, 2, 1, 1, 3, 0)
SYS_NAME = (1, 3, 6, 1, 2, 1, 1, 5, 0)
IF_DESCR = (1, 3, 6, 1, 2, 1, 2, 2, 1, 2)

HUAWEI = (1, 3, 6, 1, 4, 1, 2011)
XPON = HUAWEI + (6, 128, 1, 1, 2)
ONT_SN = XPON + (43, 1, 3)
ONT_RUN_STATUS = XPON + (46, 1, 15)
ONT_TX_POWER = XPON + (51, 1, 3)
ONT_RX_POWER = XPON + (51, 1, 4)
ENTITY = HUAWEI + (5, 25, 31, 1, 1, 1, 1)
CPU_USAGE = ENTITY + (5,)
TEMPERATURE = ENTITY + (11,)

NO_READING = 2147483647
PON_IFINDEX_BASE = 4194304000

_LAB = XPON + (500, 0)
TRAPS = {
    _LAB + (1,): "onu_offline",
    _LAB + (2,): "onu_online",
    _LAB + (3,): "onu_rx_low",
    _LAB + (4,): "olt_cpu_high",
}


def pon_name(ifindex: int) -> str:
    """4194304000 + slot*8192 + port*256 -> "0/slot/port"."""
    rest = ifindex - PON_IFINDEX_BASE
    return f"0/{rest // 8192}/{(rest % 8192) // 256}"


def _suffix(oid: Oid, base: Oid) -> Oid:
    return oid[len(base):]


def _power(value) -> float | None:
    v = int(value)
    return None if v == NO_READING else round(v / 100, 2)


def _serial(value) -> str:
    raw = bytes(value)
    return raw[:4].decode(errors="replace") + raw[4:].hex().upper() if len(raw) == 8 else raw.hex().upper()


class HuaweiDriver:
    name = "huawei"

    def matches(self, sys_object_id: Oid) -> bool:
        return tuple(sys_object_id[: len(HUAWEI)]) == HUAWEI

    async def info(self, client: SnmpClient, t: Target) -> OltInfo:
        sysv = await client.get(t, SYS_DESCR, SYS_NAME)
        descr = str(sysv[SYS_DESCR])
        ifs = await client.walk(t, IF_DESCR)
        pons = sorted(str(v).removeprefix("GPON ") for v in ifs.values() if str(v).startswith("GPON"))
        status = await client.walk(t, ONT_RUN_STATUS)
        return OltInfo(
            vendor=self.name,
            model=descr.rsplit(",", 1)[-1].strip(),
            sys_name=str(sysv[SYS_NAME]),
            pon_ports=pons,
            onus=len(status),
        )

    async def onu_status(self, client: SnmpClient, t: Target) -> list[OnuStatus]:
        status = await client.walk(t, ONT_RUN_STATUS)
        serials = await client.walk(t, ONT_SN)
        out = []
        for oid, value in status.items():
            ifx, onu = _suffix(oid, ONT_RUN_STATUS)
            sn = serials.get(ONT_SN + (ifx, onu))
            out.append(OnuStatus(pon_name(ifx), onu, _serial(sn) if sn is not None else "", int(value) == 1))
        return out

    async def onu_optical(self, client: SnmpClient, t: Target) -> list[OnuOptical]:
        rx = await client.walk(t, ONT_RX_POWER)
        tx = await client.walk(t, ONT_TX_POWER)
        out = []
        for oid, value in rx.items():
            ifx, onu = _suffix(oid, ONT_RX_POWER)
            t_val = tx.get(ONT_TX_POWER + (ifx, onu))
            out.append(OnuOptical(pon_name(ifx), onu, _power(value), _power(t_val) if t_val is not None else None))
        return out

    async def health(self, client: SnmpClient, t: Target) -> OltHealth:
        cpu = await client.walk(t, CPU_USAGE)
        temp = await client.walk(t, TEMPERATURE)
        up = await client.get(t, SYS_UPTIME)
        return OltHealth(
            cpu=max((float(v) for v in cpu.values()), default=None),
            temperature=max((float(v) for v in temp.values()), default=None),
            uptime_s=int(up[SYS_UPTIME]) / 100,
        )

    def parse_trap(self, trap_oid: Oid, binds: dict[Oid, object]) -> TrapEvent | None:
        kind = TRAPS.get(tuple(trap_oid))
        if kind is None:
            return None
        ev = TrapEvent(kind=kind, sys_name=str(binds[SYS_NAME]) if SYS_NAME in binds else None)
        for oid, value in binds.items():
            if oid[: len(ONT_RUN_STATUS)] == ONT_RUN_STATUS:
                ifx, ev.onu = _suffix(oid, ONT_RUN_STATUS)
                ev.pon = pon_name(ifx)
            elif oid[: len(ONT_SN)] == ONT_SN:
                ev.serial = _serial(value)
            elif oid[: len(ONT_RX_POWER)] == ONT_RX_POWER:
                ev.rx_dbm = _power(value)
            elif oid[: len(CPU_USAGE)] == CPU_USAGE:
                ev.cpu = float(value)
        return ev
