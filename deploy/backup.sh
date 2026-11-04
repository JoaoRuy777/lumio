#!/usr/bin/env bash
# Backup do banco (cadastros, alarmes, leituras). Guarda os 14 mais recentes.
#
#   ./deploy/backup.sh                    # manual
#   0 3 * * * /opt/lumio/deploy/backup.sh # todo dia às 3h (crontab -e)
#
# Restaurar:
#   gunzip -c backups/lumio-AAAA-MM-DD_HHMM.sql.gz | \
#     docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U lumio -d lumio
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
FILE="backups/lumio-$(date +%Y-%m-%d_%H%M).sql.gz"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-lumio}" -d "${POSTGRES_DB:-lumio}" --clean --if-exists | gzip > "$FILE"
ls -1t backups/lumio-*.sql.gz | tail -n +15 | xargs -r rm --
echo "ok: $FILE ($(du -h "$FILE" | cut -f1))"
