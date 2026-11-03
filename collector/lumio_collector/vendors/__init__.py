from ..snmp import Oid
from .base import Driver
from .huawei import HuaweiDriver

DRIVERS: dict[str, Driver] = {"huawei": HuaweiDriver()}


def detect(sys_object_id: Oid) -> Driver | None:
    """Descobre o fabricante pelo sysObjectID (prefixo enterprise)."""
    for driver in DRIVERS.values():
        if driver.matches(sys_object_id):
            return driver
    return None
