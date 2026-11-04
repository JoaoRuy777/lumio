"""Cliente SNMP assíncrono do coletor (pysnmp hlapi).

Só leitura: GET e walk por GETBULK. SNMPv2c no MVP; v3 entra trocando o
CommunityData por UsmUserData no Target.
"""

from __future__ import annotations

from dataclasses import dataclass

from pysnmp.error import PySnmpError
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    bulk_walk_cmd,
    get_cmd,
)

Oid = tuple[int, ...]


class SnmpError(Exception):
    """Falha de SNMP: timeout (OLT sem resposta) ou erro do agente."""


@dataclass(frozen=True)
class Target:
    host: str
    port: int = 161
    community: str = "public"
    timeout: float = 2.0
    retries: int = 1


class SnmpClient:
    def __init__(self, max_repetitions: int = 25):
        self.engine = SnmpEngine()
        self.max_repetitions = max_repetitions

    async def _transport(self, t: Target):
        try:
            return await UdpTransportTarget.create((t.host, t.port), timeout=t.timeout, retries=t.retries)
        except PySnmpError as e:
            # endereço que não resolve no DNS (ou inválido): é "OLT sem resposta",
            # não um erro do programa
            raise SnmpError(f"endereço {t.host!r} não encontrado") from e

    async def get(self, t: Target, *oids: Oid) -> dict[Oid, object]:
        err, status, index, binds = await get_cmd(
            self.engine,
            CommunityData(t.community, mpModel=1),
            await self._transport(t),
            ContextData(),
            *(ObjectType(ObjectIdentity(oid)) for oid in oids),
            lookupMib=False,
        )
        if err:
            raise SnmpError(str(err))
        if status:
            raise SnmpError(f"{status.prettyPrint()} no índice {index}")
        return {tuple(name): value for name, value in binds}

    async def walk(self, t: Target, base: Oid) -> dict[Oid, object]:
        """Todas as OIDs abaixo de `base`, como {oid completa: valor}."""
        out: dict[Oid, object] = {}
        async for err, status, index, binds in bulk_walk_cmd(
            self.engine,
            CommunityData(t.community, mpModel=1),
            await self._transport(t),
            ContextData(),
            0,
            self.max_repetitions,
            ObjectType(ObjectIdentity(base)),
            lexicographicMode=False,
            lookupMib=False,
        ):
            if err:
                raise SnmpError(str(err))
            if status:
                raise SnmpError(f"{status.prettyPrint()} no índice {index}")
            for name, value in binds:
                out[tuple(name)] = value
        return out

    def close(self) -> None:
        self.engine.close_dispatcher()
