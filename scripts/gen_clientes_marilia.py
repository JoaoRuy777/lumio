"""Gera a base FICTÍCIA de clientes da demonstração (Marília-SP).

    docker compose run --rm --no-deps tests python scripts/gen_clientes_marilia.py

Um cliente por ONU da rede-demo.yaml (mesmos seriais do simulador, que usa
semente fixa), com nome, telefone, endereço e coordenadas sorteados perto da
região de cada OLT. Nomes e endereços são inventados; os bairros são de
Marília apenas para o mapa fazer sentido. Saída: docs/demo/clientes-marilia.csv
(no formato que a tela Clientes importa).
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "simulator"))
from lumio_sim.model import Network  # noqa: E402

OUT = ROOT / "docs" / "demo" / "clientes-marilia.csv"

# centro aproximado de cada região e bairros (para o mapa fazer sentido)
REGIONS = {
    "olt-centro": ((-22.2140, -49.9460), ["Centro", "Fragata", "Senador Salgado Filho", "Barbosa"]),
    "olt-zona-norte": ((-22.1925, -49.9480), ["Palmital", "Jardim Maria Izabel", "Jardim Cavallari", "Nova Marília"]),
    "olt-zona-sul": ((-22.2385, -49.9430), ["Cascata", "Jardim Tangará", "Jardim Universitário", "Santa Antonieta"]),
    "olt-industrial": ((-22.2060, -49.9150), ["Distrito Industrial", "Parque das Nações", "Jardim Lavínia"]),
    "olt-rural": ((-22.2440, -49.9870), ["Padre Nóbrega", "Lácio", "Dirceu"]),
}
FIRST = ["Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Henrique", "Isabela", "João", "Karina",
         "Lucas", "Mariana", "Nicolas", "Otávio", "Paula", "Rafael", "Sabrina", "Thiago", "Vanessa", "William",
         "Beatriz", "Caio", "Débora", "Fernanda", "Gustavo", "Larissa", "Matheus", "Natália", "Pedro", "Renata",
         "Samuel", "Tatiane", "Vinícius", "Yasmin", "Leonardo", "Camila", "André", "Juliana", "Marcelo"]
LAST = ["Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves", "Pereira", "Lima", "Gomes",
        "Costa", "Ribeiro", "Martins", "Carvalho", "Almeida", "Lopes", "Soares", "Fernandes", "Vieira", "Barbosa",
        "Rocha", "Dias", "Nascimento", "Andrade", "Moreira", "Nunes", "Marques", "Machado", "Mendes", "Freitas"]
STREETS = ["Rua das Palmeiras", "Rua dos Ipês", "Rua Sete de Setembro", "Rua XV de Novembro", "Rua das Acácias",
           "Rua Santa Helena", "Rua São Paulo", "Rua Paraná", "Rua Bahia", "Rua Goiás", "Avenida das Indústrias",
           "Rua dos Girassóis", "Rua Tiradentes", "Rua Bom Jesus", "Rua das Orquídeas", "Rua Primavera",
           "Avenida Brasil", "Rua Minas Gerais", "Rua Amazonas", "Rua dos Jacarandás", "Rua Esperança"]
PLANS = ["300 Mega", "500 Mega", "500 Mega", "700 Mega", "1 Giga"]


def main() -> None:
    rng = random.Random(2026)
    cfg = yaml.safe_load((ROOT / "simulator" / "config" / "rede-demo.yaml").read_text(encoding="utf-8"))
    network = Network.from_config(cfg)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows, code = [], 10_000
    for olt in network.olts.values():
        (lat0, lon0), districts = REGIONS[olt.name]
        for pon in olt.pons.values():
            # cada PON atende uma "rua" da região: clientes da mesma PON ficam perto
            plat, plon = lat0 + rng.gauss(0, 0.005), lon0 + rng.gauss(0, 0.005)
            district, street = rng.choice(districts), rng.choice(STREETS)
            for onu in pon.onus.values():
                code += rng.randint(1, 9)
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)} {rng.choice(LAST)}"
                rows.append([
                    onu.serial, f"C{code}", name, f"(14) 9{rng.randint(6000, 9999)}-{rng.randint(1000, 9999)}",
                    f"{street}, {rng.randint(10, 2400)}", district, "Marília", rng.choice(PLANS),
                    f"{plat + rng.gauss(0, 0.0012):.6f}", f"{plon + rng.gauss(0, 0.0012):.6f}",
                ])
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["serial", "codigo", "nome", "telefone", "endereco", "bairro", "cidade", "plano", "latitude", "longitude"])
        w.writerows(rows)
    print(f"{len(rows)} clientes fictícios em {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
