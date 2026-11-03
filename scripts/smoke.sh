#!/usr/bin/env bash
# Teste de fumaça da stack inteira (usado no CI e à mão):
#   docker compose up -d --build && ./scripts/smoke.sh
#
# Cria um provedor novo, cadastra as 2 OLTs do simulador pela API (passando
# pelo nginx do painel), espera a coleta começar, provoca um rompimento de
# fibra e espera o alarme aparecer na API.
set -euo pipefail

API=${API:-http://localhost:3000/api}
# domínio comum: o validador de e-mail recusa domínios reservados (.test, .local)
EMAIL="smoke-$(date +%s)-$RANDOM@smoke.lumio.com.br"

# lê JSON do stdin e imprime uma expressão JavaScript sobre ele (d)
json() { node -e 'let s = ""; process.stdin.on("data", (c) => (s += c)).on("end", () => { const d = JSON.parse(s); console.log(eval(process.argv[1])); });' "$1"; }

wait_until() {  # wait_until <segundos> <descrição> <comando...>
  local timeout=$1 what=$2; shift 2
  for _ in $(seq 1 "$timeout"); do
    if "$@"; then echo "ok: $what"; return 0; fi
    sleep 1
  done
  echo "FALHOU: $what"; docker compose logs --tail 50 api collector worker; return 1
}

wait_until 60 "API no ar" curl -fs -o /dev/null "$API/health"
# simulador limpo: falhas de testes anteriores (ex.: fibra já rompida) não geram trap nova
curl -fsS -X POST localhost:8080/scenarios -H 'content-type: application/json' -d '{"type":"reset"}' > /dev/null

TOKEN=$(curl -fsS -X POST "$API/auth/signup" -H 'content-type: application/json' \
  -d "{\"company\":\"Smoke Test\",\"name\":\"Smoke\",\"email\":\"$EMAIL\",\"password\":\"smoke-test-123\"}" \
  | json 'd.access_token')
AUTH="Authorization: Bearer $TOKEN"
echo "ok: provedor criado ($EMAIL)"

for port in 16101 16102; do
  curl -fsS -X POST "$API/olts" -H "$AUTH" -H 'content-type: application/json' \
    -d "{\"name\":\"olt-$port\",\"host\":\"simulator\",\"snmp_port\":$port,\"community\":\"public\"}" \
    | json '`ok: OLT cadastrada, descoberta: ${d.discovery.pon_ports} PONs / ${d.discovery.onus} ONUs`'
done

olts() { curl -fsS "$API/olts" -H "$AUTH"; }
collecting() { [ "$(olts | json 'd.items.every((o) => o.collection_status === "ok")')" = "true" ]; }
fiber_cut_alarm() { [ "$(olts | json 'd.items.find((o) => o.name === "olt-16101").active_alarms')" -ge 17 ]; }

# o coletor relê o cadastro a cada 30 s
wait_until 90 "coleta das 2 OLTs em andamento" collecting
curl -fsS -X POST localhost:8080/scenarios -H 'content-type: application/json' \
  -d '{"type":"fiber_cut","olt":"olt-centro","pon":"0/1/2"}' > /dev/null
wait_until 10 "alarme de rompimento visível na API (1 PON + 16 ONUs)" fiber_cut_alarm
olts | json 'd.items.map((o) => `  ${o.name}: ${o.onus_online}/${o.onus_total} ONUs online, ${o.active_alarms} alarmes`).join("\n")'
curl -fsS -X POST localhost:8080/scenarios -H 'content-type: application/json' -d '{"type":"reset"}' > /dev/null
