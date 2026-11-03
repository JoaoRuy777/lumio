"""Perfil Huawei (MA5800): traduz o modelo da rede para OIDs SNMP.

As OIDs de leitura seguem a HUAWEI-XPON-MIB e a HUAWEI-ENTITY-EXTENT-MIB,
nos formatos usados pelos equipamentos (potência em centésimos de dBm,
índice de porta PON codificado no ifIndex). Antes de ir para produção,
conferir contra um snmpwalk de uma OLT real.

As OIDs de trap (TRAP_*) NÃO são as oficiais da Huawei: são OIDs de
laboratório, em um ramo que não existe na MIB, para o simulador e o coletor
conversarem. Trocar pelas reais quando houver uma OLT para capturar traps.
"""

from __future__ import annotations

import time

from pysnmp.proto.api import v2c

from ..model import Event, Olt, Onu

SYS_DESCR = (1, 3, 6, 1, 2, 1, 1, 1, 0)
SYS_OBJECT_ID = (1, 3, 6, 1, 2, 1, 1, 2, 0)
SYS_UPTIME = (1, 3, 6, 1, 2, 1, 1, 3, 0)
SYS_NAME = (1, 3, 6, 1, 2, 1, 1, 5, 0)
IF_DESCR = (1, 3, 6, 1, 2, 1, 2, 2, 1, 2)
IF_OPER_STATUS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 8)

HUAWEI = (1, 3, 6, 1, 4, 1, 2011)
OBJECT_ID_MA5800 = HUAWEI + (2, 248)

XPON = HUAWEI + (6, 128, 1, 1, 2)
ONT_SN = XPON + (43, 1, 3)              # hwGponDeviceOntSn
ONT_RUN_STATUS = XPON + (46, 1, 15)     # hwGponDeviceOntControlRunStatus: 1 online, 2 offline
ONT_TX_POWER = XPON + (51, 1, 3)        # hwGponOntOpticalDdmTxPower (0,01 dBm)
ONT_RX_POWER = XPON + (51, 1, 4)        # hwGponOntOpticalDdmRxPower (0,01 dBm)

ENTITY = HUAWEI + (5, 25, 31, 1, 1, 1, 1)
CPU_USAGE = ENTITY + (5,)               # hwEntityCpuUsage (%)
TEMPERATURE = ENTITY + (11,)            # hwEntityTemperature (°C)
MAIN_BOARD = 1                          # entPhysicalIndex da controladora simulada

# Valor que a Huawei devolve quando não há leitura óptica (ONU offline)
NO_READING = 2147483647

SNMP_TRAP_OID = (1, 3, 6, 1, 6, 3, 1, 1, 4, 1, 0)
_LAB = XPON + (500, 0)
TRAP_ONU_OFFLINE = _LAB + (1,)
TRAP_ONU_ONLINE = _LAB + (2,)
TRAP_ONU_RX_LOW = _LAB + (3,)
TRAP_OLT_CPU_HIGH = _LAB + (4,)


def pon_ifindex(frame: int, slot: int, port: int) -> int:
    """ifIndex de uma porta GPON na Huawei (frame 0): 4194304000 + slot*8192 + port*256."""
    if frame != 0:
        raise ValueError("o simulador só modela o frame 0")
    return 4194304000 + slot * 8192 + port * 256


def uptime(olt: Olt) -> v2c.TimeTicks:
    return v2c.TimeTicks(int((time.monotonic() - olt.started_at) * 100))


def _power(value: float, onu: Onu) -> v2c.Integer32:
    return v2c.Integer32(round(value * 100) if onu.online else NO_READING)


def _serial(onu: Onu) -> v2c.OctetString:
    return v2c.OctetString(onu.serial[:4].encode() + bytes.fromhex(onu.serial[4:]))


def build_table(olt: Olt) -> dict[tuple[int, ...], object]:
    """Todas as OIDs que a OLT responde, com o valor atual."""
    t: dict[tuple[int, ...], object] = {
        SYS_DESCR: v2c.OctetString(f"Huawei Integrated Access Software, {olt.model}"),
        SYS_OBJECT_ID: v2c.ObjectIdentifier(OBJECT_ID_MA5800),
        SYS_UPTIME: uptime(olt),
        SYS_NAME: v2c.OctetString(olt.name),
        CPU_USAGE + (MAIN_BOARD,): v2c.Integer32(round(olt.cpu)),
        TEMPERATURE + (MAIN_BOARD,): v2c.Integer32(round(olt.temperature)),
    }
    for pon in olt.pons.values():
        ifx = pon_ifindex(pon.frame, pon.slot, pon.port)
        any_online = any(o.online for o in pon.onus.values())
        t[IF_DESCR + (ifx,)] = v2c.OctetString(f"GPON {pon.name}")
        t[IF_OPER_STATUS + (ifx,)] = v2c.Integer(1 if any_online else 2)
        for onu in pon.onus.values():
            idx = (ifx, onu.onu_id)
            t[ONT_SN + idx] = _serial(onu)
            t[ONT_RUN_STATUS + idx] = v2c.Integer(1 if onu.online else 2)
            t[ONT_TX_POWER + idx] = _power(onu.tx, onu)
            t[ONT_RX_POWER + idx] = _power(onu.rx, onu)
    return t


def trap_varbinds(olt: Olt, event: Event) -> list[tuple[tuple[int, ...], object]]:
    """Varbinds de uma trap SNMPv2 para o evento (sem sysUpTime/snmpTrapOID).

    O sysName vai em toda trap para o coletor distinguir OLTs que mandam do
    mesmo IP (no simulador, todas estão no mesmo host).
    """
    name = (SYS_NAME, v2c.OctetString(olt.name))
    if event.kind == "olt_cpu_high":
        return [name, (CPU_USAGE + (MAIN_BOARD,), v2c.Integer32(round(olt.cpu)))]
    pon = olt.pon(event.pon)
    onu = pon.onus[event.onu]
    idx = (pon_ifindex(pon.frame, pon.slot, pon.port), onu.onu_id)
    binds = [
        name,
        (ONT_RUN_STATUS + idx, v2c.Integer(1 if onu.online else 2)),
        (ONT_SN + idx, _serial(onu)),
    ]
    if event.kind == "onu_rx_low":
        binds.append((ONT_RX_POWER + idx, _power(onu.rx, onu)))
    return binds


TRAP_OIDS = {
    "onu_offline": TRAP_ONU_OFFLINE,
    "onu_online": TRAP_ONU_ONLINE,
    "onu_rx_low": TRAP_ONU_RX_LOW,
    "olt_cpu_high": TRAP_OLT_CPU_HIGH,
}
