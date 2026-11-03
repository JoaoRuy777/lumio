import asyncio
import socket

import pytest

from lumio_collector.poller import OltConfig, OltWorker
from lumio_collector.sink import MemorySink
from lumio_collector.snmp import SnmpClient
from lumio_collector.traps import start_trap_receiver
from lumio_sim.model import Network
from lumio_sim.snmp_agent import TrapSender, start_agents


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def small_config(ports: list[int]) -> dict:
    return {
        "seed": 7,
        "olts": [
            {"name": f"olt-{i + 1}", "host": "127.0.0.1", "port": p, "slots": [1], "ports_per_slot": 2, "onus_per_port": 8}
            for i, p in enumerate(ports)
        ],
    }


class Lab:
    """Simulador + coletor rodando no mesmo processo, em portas livres."""

    def __init__(self, n_olts: int = 2):
        self.network = Network.from_config(small_config([free_udp_port() for _ in range(n_olts)]))
        self.trap_port = free_udp_port()
        self.traps = TrapSender(self.network, [("127.0.0.1", self.trap_port)])
        self.sink = MemorySink()
        self.client = SnmpClient()
        self.workers = [
            OltWorker(OltConfig(name=o.name, host="127.0.0.1", port=o.port, community=o.community, timeout=0.5, retries=0), self.client, self.sink)
            for o in self.network.olts.values()
        ]
        self._transports = []

    async def start(self):
        self._transports = [t for t, _ in await start_agents(self.network)]
        self.receiver = await start_trap_receiver(self.workers, "127.0.0.1", self.trap_port)
        # o coletor aprende o sysName de cada OLT na primeira coleta
        for w in self.workers:
            await w.run_once(w.collect_status)
        self.sink.records.clear()

    async def scenario(self, name: str, **params):
        events = self.network.run(name, **params)
        await self.traps.send(events)
        return events

    async def wait_for(self, predicate, timeout: float = 2.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            if predicate():
                return True
            await asyncio.sleep(0.01)
        return predicate()

    def close(self):
        for t in self._transports:
            t.close()
        self.receiver.transport.close()


@pytest.fixture
async def lab():
    lab = Lab()
    await lab.start()
    yield lab
    lab.close()


# Fixtures de banco (Postgres/Redis reais) usadas pelo worker e pela API
from tests.db_fixtures import pool, test_db_url  # noqa: E402, F401
