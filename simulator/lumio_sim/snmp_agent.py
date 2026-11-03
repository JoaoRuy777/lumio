"""Agente SNMPv2c de uma OLT simulada e envio de traps.

Implementado direto sobre os codecs do pysnmp (sem o MIB instrumentation
do pysnmp), porque o conteúdo muda a cada tick e é mais simples responder a
partir de uma tabela ordenada de OIDs.
"""

from __future__ import annotations

import asyncio
import bisect
import logging

from pyasn1.codec.ber import decoder, encoder
from pysnmp.proto import api
from pysnmp.proto.api import v2c

from .model import Event, Network, Olt
from .profiles import PROFILES

log = logging.getLogger("lumio_sim.snmp")

MAX_REPETITIONS = 50     # teto do GETBULK, para a resposta caber num datagrama
ERR_NO_ACCESS = 6


class OltAgent(asyncio.DatagramProtocol):
    def __init__(self, network: Network, olt: Olt):
        self.network = network
        self.olt = olt
        self.profile = PROFILES[olt.vendor]
        self._version = -1
        self._table: dict = {}
        self._keys: list[tuple[int, ...]] = []
        self.transport: asyncio.DatagramTransport | None = None
        self.requests = 0

    def connection_made(self, transport):
        self.transport = transport

    # ------------------------------------------------------------- tabela

    def _snapshot(self):
        if self._version != self.network.version:
            self._table = self.profile.build_table(self.olt)
            self._keys = sorted(self._table)
            self._version = self.network.version
        return self._table, self._keys

    def _get(self, oid: tuple[int, ...]):
        table, _ = self._snapshot()
        return oid, table.get(oid, v2c.NoSuchInstance(""))

    def _next(self, oid: tuple[int, ...]):
        table, keys = self._snapshot()
        i = bisect.bisect_right(keys, oid)
        if i == len(keys):
            return oid, v2c.EndOfMibView("")
        return keys[i], table[keys[i]]

    # ----------------------------------------------------------- protocolo

    def datagram_received(self, data, addr):
        if not self.olt.reachable:
            return  # OLT "fora do ar": não responde nada
        try:
            rsp = self.handle(data)
        except Exception:  # pacote malformado não pode derrubar o agente
            log.exception("erro tratando pacote de %s", addr)
            return
        if rsp is not None:
            self.transport.sendto(rsp, addr)

    def handle(self, data: bytes) -> bytes | None:
        if api.decodeMessageVersion(data) != api.SNMP_VERSION_2C:
            return None
        pmod = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]
        req_msg, _ = decoder.decode(data, asn1Spec=pmod.Message())
        if bytes(pmod.apiMessage.get_community(req_msg)) != self.olt.community.encode():
            return None  # community errada: equipamento real só ignora
        self.requests += 1
        req_pdu = pmod.apiMessage.get_pdu(req_msg)
        rsp_msg = pmod.apiMessage.get_response(req_msg)
        rsp_pdu = pmod.apiMessage.get_pdu(rsp_msg)
        req_binds = [(tuple(o), v) for o, v in pmod.apiPDU.get_varbinds(req_pdu)]

        if req_pdu.isSameTypeWith(pmod.GetRequestPDU()):
            binds = [self._get(o) for o, _ in req_binds]
        elif req_pdu.isSameTypeWith(pmod.GetNextRequestPDU()):
            binds = [self._next(o) for o, _ in req_binds]
        elif req_pdu.isSameTypeWith(pmod.GetBulkRequestPDU()):
            binds = self._bulk(pmod, req_pdu, req_binds)
        else:  # SET e afins: a Lumio só lê, o simulador também não aceita escrita
            pmod.apiPDU.set_error_status(rsp_pdu, ERR_NO_ACCESS)
            pmod.apiPDU.set_error_index(rsp_pdu, 1)
            binds = req_binds

        pmod.apiPDU.set_varbinds(rsp_pdu, binds)
        return encoder.encode(rsp_msg)

    def _bulk(self, pmod, req_pdu, req_binds):
        n = min(int(pmod.apiBulkPDU.get_non_repeaters(req_pdu)), len(req_binds))
        m = min(int(pmod.apiBulkPDU.get_max_repetitions(req_pdu)), MAX_REPETITIONS)
        binds = [self._next(o) for o, _ in req_binds[:n]]
        cursors = [o for o, _ in req_binds[n:]]
        for _ in range(m):
            if not cursors:
                break
            row = [self._next(o) for o in cursors]
            binds += row
            cursors = [o for o, _ in row]
            if all(isinstance(v, v2c.EndOfMibView) for _, v in row):
                break
        return binds


class TrapSender:
    """Manda traps SNMPv2c das OLTs simuladas para o coletor."""

    def __init__(self, network: Network, targets: list[tuple[str, int]]):
        self.network = network
        self.targets = targets
        self.sent = 0
        self._transport: asyncio.DatagramTransport | None = None

    def encode(self, event: Event) -> bytes | None:
        olt = self.network.olt(event.olt)
        profile = PROFILES[olt.vendor]
        trap_oid = profile.TRAP_OIDS.get(event.kind)
        if trap_oid is None:
            return None
        pmod = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]
        pdu = pmod.TrapPDU()
        pmod.apiTrapPDU.set_defaults(pdu)
        pmod.apiTrapPDU.set_varbinds(
            pdu,
            [(pmod.apiTrapPDU.sysUpTime, profile.uptime(olt)), (pmod.apiTrapPDU.snmpTrapOID, v2c.ObjectIdentifier(trap_oid))]
            + profile.trap_varbinds(olt, event),
        )
        msg = pmod.Message()
        pmod.apiMessage.set_defaults(msg)
        pmod.apiMessage.set_community(msg, olt.community)
        pmod.apiMessage.set_pdu(msg, pdu)
        return encoder.encode(msg)

    async def send(self, events: list[Event]) -> None:
        if not events or not self.targets:
            return
        if self._transport is None:
            loop = asyncio.get_running_loop()
            self._transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=("0.0.0.0", 0))
        for event in events:
            data = self.encode(event)
            if data is None:
                continue
            for target in self.targets:
                self._transport.sendto(data, target)
                self.sent += 1


async def start_agents(network: Network) -> list[tuple[asyncio.DatagramTransport, OltAgent]]:
    loop = asyncio.get_running_loop()
    started = []
    for olt in network.olts.values():
        transport, agent = await loop.create_datagram_endpoint(
            lambda o=olt: OltAgent(network, o), local_addr=(olt.host, olt.port)
        )
        log.info("OLT %s (%s %s) ouvindo SNMP em %s:%s", olt.name, olt.vendor, olt.model, olt.host, olt.port)
        started.append((transport, agent))
    return started
