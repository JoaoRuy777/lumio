"""Receptor de traps SNMPv2c: transforma cada trap em um evento na hora,
sem esperar o próximo ciclo de polling."""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import asdict

from pyasn1.codec.ber import decoder
from pysnmp.proto import api

from .poller import OltWorker, now
from .vendors import DRIVERS

log = logging.getLogger("lumio_collector.traps")

SNMP_TRAP_OID = (1, 3, 6, 1, 6, 3, 1, 1, 4, 1, 0)


def _resolve(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return host


class TrapReceiver(asyncio.DatagramProtocol):
    def __init__(self, workers: list[OltWorker]):
        self.workers = workers
        self.by_ip: dict[str, list[OltWorker]] = {}
        for w in workers:
            self.by_ip.setdefault(_resolve(w.cfg.host), []).append(w)
        self.received = 0
        self.ignored = 0
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport):
        self.transport = transport

    def _find(self, src_ip: str, sys_name: str | None) -> OltWorker | None:
        candidates = self.by_ip.get(src_ip, [])
        if len(candidates) <= 1 or sys_name is None:
            return candidates[0] if len(candidates) == 1 else None
        for w in candidates:
            if sys_name in (w.sys_name, w.cfg.name):
                return w
        return None

    def datagram_received(self, data, addr):
        try:
            asyncio.get_running_loop().create_task(self.handle(data, addr[0]))
        except Exception:
            log.exception("erro agendando trap de %s", addr)

    async def handle(self, data: bytes, src_ip: str) -> None:
        received_at = now()
        try:
            if api.decodeMessageVersion(data) != api.SNMP_VERSION_2C:
                self.ignored += 1
                return
            pmod = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]
            msg, _ = decoder.decode(data, asn1Spec=pmod.Message())
            pdu = pmod.apiMessage.get_pdu(msg)
            if not pdu.isSameTypeWith(pmod.TrapPDU()):
                self.ignored += 1
                return
            binds = {tuple(o): v for o, v in pmod.apiPDU.get_varbinds(pdu)}
            community = str(pmod.apiMessage.get_community(msg))
        except Exception:
            log.warning("pacote inválido de %s", src_ip)
            self.ignored += 1
            return

        trap_oid = tuple(binds.get(SNMP_TRAP_OID, ()))
        # Tenta todos os drivers só para descobrir o sysName antes de achar a OLT
        event = None
        for driver in DRIVERS.values():
            event = driver.parse_trap(trap_oid, binds)
            if event:
                break
        worker = self._find(src_ip, event.sys_name if event else None)
        if worker is None or event is None or community != worker.cfg.community:
            log.info("trap ignorada de %s (oid %s)", src_ip, ".".join(map(str, trap_oid)))
            self.ignored += 1
            return
        self.received += 1
        fields = {k: v for k, v in asdict(event).items() if k not in ("kind", "sys_name") and v is not None}
        await worker.sink.publish({
            "type": "event", "olt": worker.cfg.name, "ts": received_at,
            "kind": event.kind, "source": "trap", **fields,
        })


async def start_trap_receiver(workers: list[OltWorker], host: str, port: int) -> TrapReceiver:
    loop = asyncio.get_running_loop()
    _, receiver = await loop.create_datagram_endpoint(lambda: TrapReceiver(workers), local_addr=(host, port))
    log.info("recebendo traps em %s:%s", host, port)
    return receiver
