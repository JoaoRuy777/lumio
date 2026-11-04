#!/usr/bin/env bash
# Teste de carga completo (sprint 6). Leva uns 20 minutos.
#
#   docker compose down            # a stack principal usa as mesmas portas
#   ./scripts/bench/bench.sh       # ou LEVELS="2 10" ./scripts/bench/bench.sh
#
# Roda num projeto compose separado (lumio-bench), com banco próprio que é
# apagado no fim: não mexe nos dados da stack principal. Resultados em
# scripts/bench/out/ e o relatório em docs/resultados.md.
set -euo pipefail
cd "$(dirname "$0")/../.."

LEVELS=${LEVELS:-"2 10 25 50"}
OUT=scripts/bench/out
DC=(docker compose -p lumio-bench -f docker-compose.yml -f scripts/bench/docker-compose.bench.yml)
RUN=("${DC[@]}" --profile test run --rm -T tests)

if [ -n "$(docker compose ps -q 2>/dev/null)" ]; then
  echo "A stack principal está no ar e usa as mesmas portas. Rode 'docker compose down' antes."; exit 1
fi

mkdir -p "$OUT"
rm -f "$OUT"/nivel-*.json "$OUT"/stats.csv "$OUT"/.stop
docker info --format 'Docker {{.ServerVersion}} ({{.OperatingSystem}}), VM com {{.NCPU}} CPUs e {{.MemTotal}} bytes de RAM' > "$OUT/ambiente.txt"
"${DC[@]}" --profile test build
"${RUN[@]}" python scripts/bench/gen_network.py "${LEVELS%% *}" "$OUT/rede.yaml"
"${DC[@]}" up -d

# CPU e memória de cada contêiner, durante tudo (o relatório recorta por nível)
(
  while [ ! -f "$OUT/.stop" ]; do
    ts=$(date +%s)
    docker stats --no-stream --format '{{.Name}};{{.CPUPerc}};{{.MemUsage}}' | grep '^lumio-bench-' \
      | sed "s/^/$ts;/" >> "$OUT/stats.csv" || true
  done
) &
SAMPLER=$!
trap 'touch "$OUT/.stop"; wait $SAMPLER 2>/dev/null || true' EXIT

for N in $LEVELS; do
  echo "== nível: $N OLTs ($((N * 128)) ONUs)"
  "${RUN[@]}" python scripts/bench/gen_network.py "$N" "$OUT/rede.yaml"
  "${DC[@]}" up -d --force-recreate simulator
  sleep 5
  "${RUN[@]}" python scripts/bench/run.py --olts "$N" --out "$OUT/nivel-$N.json"
  sleep 35      # o coletor relê o cadastro (OLTs removidas) antes do próximo nível
done

touch "$OUT/.stop"; wait $SAMPLER || true
"${RUN[@]}" python scripts/bench/report.py "$OUT" docs
"${DC[@]}" --profile test down -v
echo "pronto: docs/resultados.md"
