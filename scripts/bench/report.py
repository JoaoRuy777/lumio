"""Gera docs/resultados.md e os gráficos a partir das medições do bench.sh.

    python scripts/bench/report.py scripts/bench/out docs

Gráficos (regras de visualização usadas):
- um eixo só por gráfico; marcas finas (linha 2 px, marcador >= 8 px);
- cor fixa por série e na mesma ordem em todos os gráficos (a cor segue o
  serviço, não a posição); paleta validada para daltonismo;
- legenda sempre que há 2+ séries e rótulo direto no último ponto; forma de
  marcador diferente por série (a informação não depende só da cor);
- toda figura tem a tabela correspondente no texto.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# paleta categórica validada (slots 1-4), texto e grade recessivos
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
MARKERS = ["o", "s", "^", "D"]
TEXT, MUTED, GRID = "#0b0b0b", "#52514e", "#e7e5e4"
SERVICES = ["collector", "worker", "postgres", "api"]          # ordem fixa = cor fixa
OTHER_SERVICES = ["redis", "notifier", "web", "mailpit"]
SERVICE_LABEL = {"collector": "coletor", "worker": "worker", "postgres": "Postgres", "api": "API",
                 "redis": "Redis", "notifier": "notificador", "web": "painel (nginx)", "mailpit": "Mailpit",
                 "simulator": "simulador"}


def mib(text: str) -> float:
    m = re.match(r"([\d.]+)\s*([KMG]i?B)", text.strip())
    if not m:
        return 0.0
    value, unit = float(m.group(1)), m.group(2)
    return value * {"KiB": 1 / 1024, "KB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}[unit]


def load(out: Path) -> tuple[list[dict], list[tuple[float, str, float, float]]]:
    levels = sorted((json.loads(p.read_text()) for p in out.glob("nivel-*.json")), key=lambda r: r["olts"])
    samples = []
    stats = out / "stats.csv"
    if stats.exists():
        for row in csv.reader(stats.open(encoding="utf-8"), delimiter=";"):
            if len(row) < 4:
                continue
            ts, name, cpu, mem = row[0], row[1], row[2], row[3]
            m = re.match(r"lumio-bench-(\w+)-\d+", name)
            if m:
                samples.append((float(ts), m.group(1), float(cpu.rstrip("%") or 0), mib(mem.split("/")[0])))
    return levels, samples


def resources(level: dict, samples) -> dict[str, dict]:
    start, end = level["window"]["start"], level["window"]["end"]
    by: dict[str, dict[str, list[float]]] = {}
    for ts, svc, cpu, mem in samples:
        if start <= ts <= end:
            d = by.setdefault(svc, {"cpu": [], "mem": []})
            d["cpu"].append(cpu)
            d["mem"].append(mem)
    return {svc: {"cpu_mean": round(statistics.fmean(v["cpu"]), 1), "cpu_max": round(max(v["cpu"]), 1),
                  "mem_mean": round(statistics.fmean(v["mem"]), 1), "mem_max": round(max(v["mem"]), 1),
                  "samples": len(v["cpu"])} for svc, v in by.items()}


# ------------------------------------------------------------------ gráficos

def style(ax, title: str, ylabel: str, xlabel: str = "ONUs monitoradas"):
    ax.set_title(title, loc="left", fontsize=12, color=TEXT, pad=12)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0)


def lines(path: Path, title: str, ylabel: str, xs: list[int], series: list[tuple[str, list[float | None]]], fmt="{:.0f}"):
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=160)
    for i, (label, ys) in enumerate(series):
        pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
        if not pts:
            continue
        px, py = zip(*pts)
        ax.plot(px, py, color=SERIES[i], linewidth=2, marker=MARKERS[i], markersize=6,
                markeredgecolor="white", markeredgewidth=1.5, label=label)
        # rótulo direto no último ponto, com a cor de texto (não a da série)
        ax.annotate(f"{label}: {fmt.format(py[-1])}", (px[-1], py[-1]), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=8, color=TEXT)
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{x:,}".replace(",", ".") for x in xs])
    ax.set_ylim(bottom=0)
    ax.set_xlim(right=max(xs) * 1.25)
    style(ax, title, ylabel)
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=8, loc="upper left", labelcolor=TEXT)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def bars(path: Path, title: str, ylabel: str, xs: list[int], ys: list[float], fmt="{:,.0f}"):
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=160)
    labels = [f"{x:,}".replace(",", ".") for x in xs]
    ax.bar(labels, ys, color=SERIES[0], width=0.5)
    for i, y in enumerate(ys):
        ax.annotate(fmt.format(y).replace(",", "."), (i, y), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=8, color=TEXT)
    ax.set_ylim(bottom=0, top=max(ys) * 1.15)
    style(ax, title, ylabel)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ------------------------------------------------------------------ texto

def n(v, digits=0) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join([" --- "] + [" ---: "] * (len(header) - 1)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def environment(out: Path) -> str:
    env = (out / "ambiente.txt").read_text(encoding="utf-8").strip() if (out / "ambiente.txt").exists() else ""
    cpu = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines()
                if l.startswith("model name")), "?") if Path("/proc/cpuinfo").exists() else "?"
    return f"- CPU: {cpu}\n" + "\n".join(f"- {l}" for l in env.splitlines() if l)


def before_after(figs: Path, levels: list[dict]) -> str:
    """Compara com uma medição guardada antes de uma otimização (antes-nivel-N.json)."""
    rows = []
    for path in sorted(figs.glob("antes-nivel-*.json")):
        old = json.loads(path.read_text(encoding="utf-8"))
        new = next((l for l in levels if l["olts"] == old["olts"]), None)
        if new is None:
            continue
        for label, key in (("rajada de estado (ONUs/s)", "burst"), ("rajada de potência (ONUs/s)", "burst_optical")):
            a, b = old[key]["onus_per_s"], new[key]["onus_per_s"]
            rows.append([n(old["onus"]), label, n(a), n(b), f"{b / a:.1f}×".replace(".", ",")])
        a, b = old["alarms"]["latency_total_ms"]["p50"], new["alarms"]["latency_total_ms"]["p50"]
        rows.append([n(old["onus"]), "latência de alarme p50 (ms)", n(a, 1), n(b, 1), "—"])
    if not rows:
        return ""
    return "## Antes e depois da otimização do worker\n\n" + \
        "Mesmo nível, medido antes e depois de o worker passar a gravar o estado e a potência\n" + \
        "das ONUs em lote (uma consulta por OLT em vez de uma por ONU).\n\n" + \
        table(["ONUs", "medida", "antes", "depois", "ganho"], rows) + "\n"


def main(out: Path, docs: Path) -> None:
    levels, samples = load(out)
    if not levels:
        sys.exit("nenhum resultado em " + str(out))
    figs = docs / "resultados"
    figs.mkdir(parents=True, exist_ok=True)
    xs = [l["onus"] for l in levels]
    res = [resources(l, samples) for l in levels]

    lat = [l["alarms"]["latency_total_ms"] for l in levels]
    lines(figs / "latencia.png", "Latência da falha até o alarme gravado (ms)", "milissegundos", xs,
          [("p50", [x["p50"] for x in lat]), ("p95", [x["p95"] for x in lat]), ("p99", [x["p99"] for x in lat])])
    lines(figs / "cpu.png", "CPU média por serviço durante a medição (%)", "% de 1 núcleo", xs,
          [(SERVICE_LABEL[s], [r.get(s, {}).get("cpu_mean") for r in res]) for s in SERVICES], fmt="{:.1f}")
    lines(figs / "memoria.png", "Memória média por serviço (MiB)", "MiB", xs,
          [(SERVICE_LABEL[s], [r.get(s, {}).get("mem_mean") for r in res]) for s in SERVICES])
    bars(figs / "vazao.png", "Vazão do worker numa rajada (ONUs processadas por segundo)", "ONUs/s", xs,
         [l["burst"]["onus_per_s"] for l in levels])
    poll = [l["polling"]["took_ms"] for l in levels]
    lines(figs / "coleta.png", "Duração da coleta de estado de uma OLT (128 ONUs, ms)", "milissegundos", xs,
          [("p50", [p["p50"] for p in poll]), ("p95", [p["p95"] for p in poll])])

    (figs / "dados.json").write_text(json.dumps({"levels": levels, "resources": res}, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    analysis = (figs / "analise.md").read_text(encoding="utf-8") if (figs / "analise.md").exists() else ""
    total_mem = [sum(v["mem_mean"] for s, v in r.items() if s != "simulator") for r in res]
    total_cpu = [sum(v["cpu_mean"] for s, v in r.items() if s != "simulator") for r in res]

    md = f"""# Resultados: desempenho da Lumio

> Gerado por `scripts/bench/report.py` a partir de `scripts/bench/bench.sh`.
> Para refazer: `docker compose down && ./scripts/bench/bench.sh` (uns 20 minutos).

## Metodologia

**Ambiente.** Uma máquina só, com todos os serviços em contêineres Docker
(mesmo `docker-compose.yml` do desenvolvimento, sem ajustes de desempenho):

{environment(out)}

**Carga.** O simulador de OLTs da sprint 1 sobe com N OLTs Huawei MA5800-X7,
cada uma com 4 portas PON e 32 ONUs por porta (128 ONUs). Foram medidos os
níveis de {", ".join(str(l["olts"]) for l in levels)} OLTs ({", ".join(n(x) for x in xs)} ONUs). Em cada nível:

1. um provedor novo é criado e as N OLTs são cadastradas pela API, como um
   usuário faria (com a descoberta de portas e ONUs);
2. espera-se todas as OLTs entrarem em coleta (o coletor relê o cadastro a
   cada 30 s); a coleta segue os intervalos padrão: estado a cada 60 s e
   potência óptica a cada 5 min;
3. **janela de medição**: {levels[0]["alarms"]["faults"]} quedas de ONU, uma por segundo, em ONUs
   sorteadas (semente fixa), seguidas de {int(levels[0]["window"]["end"] - levels[0]["window"]["start"]) - levels[0]["alarms"]["faults"]} s de observação
   (pelo menos um ciclo completo de coleta). A **latência** de cada queda é o
   tempo entre o pedido ao simulador e a gravação do alarme no Postgres
   (`alarms.created_at`); todos os contêineres usam o relógio do host;
4. CPU e memória de cada contêiner são amostradas com `docker stats` durante
   todo o teste; as tabelas usam só as amostras de dentro da janela;
5. **rajada**: {levels[0]["burst"]["records"]} registros de estado (128 ONUs cada) e depois o mesmo número
   de leituras de potência são injetados de
   uma vez na fila do Redis, e mede-se o tempo até o worker zerá-la. Isso dá a
   vazão máxima do worker, independente do simulador.

As OLTs de um nível são removidas antes do próximo, então a carga de cada
nível é só a dele. O simulador também roda na mesma máquina e disputa CPU
com a Lumio; o consumo dele aparece separado e não entra nos totais.

## Latência de alarme

Do pedido de falha ao simulador até o alarme gravado no banco. Inclui: o
simulador mudar o estado e mandar a trap SNMP, o coletor receber e publicar
no Redis, o worker consumir, aplicar as regras e gravar.

![Latência da falha até o alarme](resultados/latencia.png)

{table(["ONUs", "OLTs", "quedas", "sem alarme", "p50 (ms)", "p95 (ms)", "p99 (ms)", "máx. (ms)", "coletor→banco p50 (ms)"],
       [[n(l["onus"]), l["olts"], l["alarms"]["faults"], l["alarms"]["missing_alarms"], n(t["p50"], 1), n(t["p95"], 1),
         n(t["p99"], 1), n(t["max"], 1), n(l["alarms"]["latency_pipeline_ms"]["p50"], 1)]
        for l, t in zip(levels, lat)])}

## Coleta SNMP e vazão do worker

Duração da coleta de estado de uma OLT (128 ONUs, GETBULK) e a vazão do
worker na rajada.

![Duração da coleta](resultados/coleta.png)

![Vazão do worker](resultados/vazao.png)

{table(["ONUs", "coletas medidas", "coleta p50 (ms)", "coleta p95 (ms)", "ONUs/s por OLT (p50)", "rajada (s)", "worker (registros/s)", "worker (ONUs/s)", "worker, potência (ONUs/s)"],
       [[n(l["onus"]), l["polling"]["status_polls"], n(l["polling"]["took_ms"]["p50"]), n(l["polling"]["took_ms"]["p95"]),
         n(l["polling"]["onus_per_s_per_olt"]["p50"]), n(l["burst"]["seconds"], 2), n(l["burst"]["records_per_s"], 1),
         n(l["burst"]["onus_per_s"]), n(l["burst_optical"]["onus_per_s"])] for l in levels])}

Para comparação: no maior nível, a coleta normal gera {n(levels[-1]["onus"] / 60)} estados de ONU por
segundo (todas as ONUs a cada 60 s).

## CPU e memória

Média dentro da janela de medição; CPU em % de um núcleo (100 % = um núcleo inteiro).

![CPU por serviço](resultados/cpu.png)

![Memória por serviço](resultados/memoria.png)

{table(["ONUs"] + [f"{SERVICE_LABEL[s]} CPU %" for s in SERVICES] + ["Lumio total CPU %", "simulador CPU %"],
       [[n(l["onus"])] + [n(r.get(s, {}).get("cpu_mean"), 1) for s in SERVICES] + [n(tc, 1), n(r.get("simulator", {}).get("cpu_mean"), 1)]
        for l, r, tc in zip(levels, res, total_cpu)])}

{table(["ONUs"] + [f"{SERVICE_LABEL[s]} MiB" for s in SERVICES + OTHER_SERVICES] + ["Lumio total MiB"],
       [[n(l["onus"])] + [n(r.get(s, {}).get("mem_mean")) for s in SERVICES + OTHER_SERVICES] + [n(tm)]
        for l, r, tm in zip(levels, res, total_mem)])}

## Cadastro

{table(["ONUs", "OLTs", "descoberta por OLT p50 (ms)", "descoberta p95 (ms)", "até todas em coleta (s)"],
       [[n(l["onus"]), l["olts"], n(l["discovery_ms"]["p50"]), n(l["discovery_ms"]["p95"]), n(l["ready_s"])] for l in levels])}

"Até todas em coleta" inclui a espera de até 30 s do coletor reler o cadastro.

{before_after(figs, levels)}
{analysis}
"""
    (docs / "resultados.md").write_text(md, encoding="utf-8")
    print(f"ok: {docs / 'resultados.md'} e {len(list(figs.glob('*.png')))} gráficos")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
