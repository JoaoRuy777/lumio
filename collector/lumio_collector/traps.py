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
        self.workers: list[OltWorker] = []
        self.by_ip: dict[str, list[OltWorker]] = {}
        self.set_workers(workers)
        self.received = 0
        self.ignored = 0
        self.transport: asyncio.DatagramTransport | None = None

    def set_workers(self, workers: list[OltWorker]) -> None:
        """Troca a lista de OLTs (o cadastro na API muda com o coletor rodando)."""
        by_ip: dict[str, list[OltWorker]] = {}
        for w in workers:
            by_ip.setdefault(_resolve(w.cfg.host), []).append(w)
        self.workers, self.by_ip = list(workers), by_ip

    def connection_made(self, transport):
        self.transport = transport

    def _find(self, src_ip: str, sys_name: str | None) -> list[OltWorker]:
        """OLTs cadastradas que correspondem à trap.

        Várias OLTs no mesmo IP (o simulador, ou um NAT) são separadas pelo
        sysName. A mesma OLT cadastrada por dois provedores recebe a trap nos dois.
        """
        candidates = self.by_ip.get(src_ip, [])
        if sys_name is not None:
            named = [w for w in candidates if sys_name in (w.sys_name, w.cfg.sys_name, w.cfg.name)]
            if named:
                return named
        # sem sysName que desempate: só serve se todas apontam para o mesmo equipamento
        same_device = len({(w.cfg.host, w.cfg.port) for w in candidates}) == 1
        return candidates if same_device else []

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
        matches = [] if event is None else [
            w for w in self._find(src_ip, event.sys_name) if community == w.cfg.community]
        if not matches:
            log.info("trap ignorada de %s (oid %s)", src_ip, ".".join(map(str, trap_oid)))
            self.ignored += 1
            return
        self.received += 1
        fields = {k: v for k, v in asdict(event).items() if k not in ("kind", "sys_name") and v is not None}
        for worker in matches:
            await worker.sink.publish({
                "type": "event", **worker.identity(), "ts": received_at,
                "kind": event.kind, "source": "trap", **fields,
            })


async def start_trap_receiver(workers: list[OltWorker], host: str, port: int) -> TrapReceiver:
    loop = asyncio.get_running_loop()
    _, receiver = await loop.create_datagram_endpoint(lambda: TrapReceiver(workers), local_addr=(host, port))
    log.info("recebendo traps em %s:%s", host, port)
    return receiver
