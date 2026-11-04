"""Os casos de demonstração (lumio_sim.demo) batem com a rede-demo.yaml."""

from pathlib import Path

import pytest
import yaml

from lumio_sim.demo import CASES
from lumio_sim.model import Network

CONFIG = Path(__file__).resolve().parents[1] / "simulator" / "config" / "rede-demo.yaml"


@pytest.mark.parametrize("case", list(CASES))
def test_caso_roda_na_rede_demo(case):
    net = Network.from_config(yaml.safe_load(CONFIG.read_text(encoding="utf-8")))
    for scenario in CASES[case][1]:
        params = {k: v for k, v in scenario.items() if k != "type"}
        net.run(scenario["type"], **params)        # OLT, PON ou ONU inexistente levanta LookupError
    net.run("reset")
    assert all(o.reachable and all(n.online for p in o.pons.values() for n in p.onus.values())
               for o in net.olts.values())
