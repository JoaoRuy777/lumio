"""Casos críticos prontos para a demonstração (rede-demo.yaml).

    docker compose -p lumio-coleta exec simulator python -m lumio_sim.demo criticos
    docker compose -p lumio-coleta exec simulator python -m lumio_sim.demo normalizar
    docker compose -p lumio-coleta exec simulator python -m lumio_sim.demo <caso>

Cada caso provoca um tipo de alarme da Lumio. "criticos" aplica todos de uma
vez; "normalizar" volta a rede ao normal (os alarmes se encerram sozinhos).
Fala com a API de cenários do próprio simulador (http://localhost:8080).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

API = os.environ.get("LUMIO_SIM_API", "http://localhost:8080")

# caso -> (o que mostra no painel, cenários)
CASES: dict[str, tuple[str, list[dict]]] = {
    "rompimento": ("CRÍTICO: rompimento de fibra na olt-zona-sul, PON 0/1/1 (16 ONUs caem juntas, viram 1 alarme)",
                   [{"type": "fiber_cut", "olt": "olt-zona-sul", "pon": "0/1/1"}]),
    "olt-fora": ("CRÍTICO: olt-rural para de responder (detectado pela falta de resposta, em até 1 min)",
                 [{"type": "olt_down", "olt": "olt-rural"}]),
    "cpu": ("MAIOR: CPU da olt-industrial em 96 %",
            [{"type": "overload", "olt": "olt-industrial", "cpu": 96}]),
    "onus-offline": ("MENOR: 3 ONUs da olt-centro offline, em PONs diferentes (não é rompimento)",
                     [{"type": "onu_down", "olt": "olt-centro", "pon": "0/1/0", "onu": 3, "cause": "dying_gasp"},
                      {"type": "onu_down", "olt": "olt-centro", "pon": "0/1/2", "onu": 7, "cause": "los"},
                      {"type": "onu_down", "olt": "olt-centro", "pon": "0/1/3", "onu": 12, "cause": "los"}]),
    "sinal-baixo": ("AVISO: sinal de 4 ONUs da olt-zona-norte caindo até -31 dBm (alarme ao passar de -27 dBm, ~2 min)",
                    [{"type": "degrade", "olt": "olt-zona-norte", "pon": pon, "onu": onu,
                      "rate_db_per_min": 4.0, "target_dbm": -31.0}
                     for pon, onu in (("0/1/0", 5), ("0/1/0", 6), ("0/1/1", 20), ("0/1/1", 21))]),
}


def post(body: dict) -> dict:
    req = urllib.request.Request(f"{API}/scenarios", json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def main(argv: list[str]) -> int:
    choice = argv[0] if argv else ""
    if choice == "normalizar":
        post({"type": "reset"})
        print("rede normalizada: os alarmes se encerram nas próximas leituras")
        return 0
    names = list(CASES) if choice == "criticos" else [choice] if choice in CASES else []
    if not names:
        print(__doc__.split("\n\n")[0] + "\n\ncasos: criticos, normalizar, " + ", ".join(CASES))
        return 2
    for name in names:
        label, scenarios = CASES[name]
        for s in scenarios:
            post(s)
        print(f"- {name}: {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
