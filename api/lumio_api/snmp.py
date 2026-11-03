"""Testar conexão e descoberta: reaproveita o código do coletor (mesmos drivers)."""

from __future__ import annotations

from dataclasses import asdict

from lumio_collector.poller import SYS_OBJECT_ID, probe
from lumio_collector.snmp import SnmpClient, SnmpError, Target
from lumio_collector.vendors import detect


async def test_connection(client: SnmpClient, host: str, port: int, community: str, timeout: float = 2.0, retries: int = 1) -> dict:
    """{"ok": True, "vendor", "model", "sys_name", "pon_ports", "onus"} ou {"ok": False, "error"}."""
    try:
        return await probe(client, Target(host, port, community, timeout, retries))
    except SnmpError as e:
        return {"ok": False, "error": f"sem resposta SNMP de {host}:{port} (confira IP, porta e community): {e}"}


async def discover(client: SnmpClient, host: str, port: int, community: str, timeout: float = 2.0, retries: int = 1) -> dict:
    """Identifica a OLT e lista as ONUs de cada PON."""
    target = Target(host, port, community, timeout, retries)
    try:
        sys_oid = (await client.get(target, SYS_OBJECT_ID))[SYS_OBJECT_ID]
        driver = detect(tuple(sys_oid))
        if driver is None:
            return {"ok": False, "error": f"fabricante não suportado (sysObjectID {sys_oid.prettyPrint()})"}
        info = await driver.info(client, target)
        onus = await driver.onu_status(client, target)
    except SnmpError as e:
        return {"ok": False, "error": f"sem resposta SNMP de {host}:{port}: {e}"}
    return {"ok": True, **asdict(info), "onu_list": [asdict(o) for o in onus]}
