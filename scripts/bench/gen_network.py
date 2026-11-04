"""Gera a rede do simulador para o teste de carga: N OLTs MA5800-X7 com
4 PONs x 32 ONUs = 128 ONUs cada.

    python scripts/bench/gen_network.py 50 scripts/bench/out/rede.yaml
"""

import sys
from pathlib import Path

import yaml

ONUS_PER_OLT = 128


def network(n_olts: int) -> dict:
    return {
        "seed": 2026,
        "base_port": 16101,
        "olts": [
            {"name": f"olt-{i + 1:03d}", "model": "MA5800-X7", "host": "0.0.0.0", "community": "public",
             "slots": [1], "ports_per_slot": 4, "onus_per_port": 32}
            for i in range(n_olts)
        ],
    }


if __name__ == "__main__":
    n, out = int(sys.argv[1]), Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(network(n), sort_keys=False), encoding="utf-8")
    print(f"{n} OLTs, {n * ONUS_PER_OLT} ONUs -> {out}")
