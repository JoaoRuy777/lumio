#!/usr/bin/env bash
# Teste de fumaça da stack inteira (usado no CI e à mão):
#   docker compose up -d --build && ./scripts/smoke.sh
# Provoca um rompimento de fibra no simulador e espera o alarme no Postgres.
set -euo pipefail

psql() { docker compose exec -T postgres psql -U "${POSTGRES_USER:-lumio}" -d "${POSTGRES_DB:-lumio}" -tAc "$1"; }

wait_until() {  # wait_until <segundos> <descrição> <comando...>
  local timeout=$1 what=$2; shift 2
  for _ in $(seq 1 "$timeout"); do
    if "$@"; then echo "ok: $what"; return 0; fi
    sleep 1
  done
  echo "FALHOU: $what"; docker compose logs --tail 50 collector worker; return 1
}

inventory_ready() { [ "$(psql 'select count(*) from onus where online')" = "128" ]; }
fiber_cut_alarm() { [ "$(psql "select count(*) from alarms where kind = 'pon_fiber_cut' and status = 'active'")" = "1" ]; }

wait_until 120 "inventário com 128 ONUs online" inventory_ready
curl -fsS -X POST localhost:8080/scenarios -H 'content-type: application/json' \
  -d '{"type":"fiber_cut","olt":"olt-centro","pon":"0/1/2"}' > /dev/null
wait_until 10 "alarme de rompimento de fibra no banco" fiber_cut_alarm
psql "select kind, severity, round(latency_ms::numeric, 1) || ' ms' from alarms where kind = 'pon_fiber_cut' and status = 'active'"
