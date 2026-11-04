#!/usr/bin/env bash
# Gera o .env de produção com senhas e chaves aleatórias.
#
#   ./deploy/gen-env.sh lumio.seudominio.com.br voce@seudominio.com.br
#
# Depois, edite o .env e preencha o SMTP (veja docs/deploy.md).
set -euo pipefail
cd "$(dirname "$0")/.."

DOMAIN=${1:?uso: ./deploy/gen-env.sh <domínio> <e-mail para o certificado>}
ACME=${2:?uso: ./deploy/gen-env.sh <domínio> <e-mail para o certificado>}
if [ -e .env ]; then echo ".env já existe; apague ou renomeie antes (não sobrescrevo segredos)."; exit 1; fi

rand() { openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-"$1"; }
# chave Fernet: 32 bytes em base64 "url-safe"
fernet() { openssl rand -base64 32 | tr '+/' '-_'; }

umask 077
cat > .env <<ENV
# Gerado por deploy/gen-env.sh em $(date -u +%Y-%m-%dT%H:%MZ). NÃO vai para o git.
LUMIO_DOMAIN=$DOMAIN
ACME_EMAIL=$ACME

POSTGRES_DB=lumio
POSTGRES_USER=lumio
POSTGRES_PASSWORD=$(rand 32)
LUMIO_APP_DB_PASSWORD=$(rand 32)
LUMIO_SYSTEM_DB_PASSWORD=$(rand 32)

LUMIO_JWT_SECRET=$(rand 64)
LUMIO_SECRET_KEY=$(fernet)
LUMIO_SERVICE_TOKEN=$(rand 48)
LUMIO_RETENTION_DAYS=90

# SMTP: preencha com o do seu provedor de e-mail (ex.: Brevo, Amazon SES, Resend)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=Lumio <alertas@$DOMAIN>
SMTP_SECURITY=starttls
ENV
echo "ok: .env criado (permissão 600). Falta preencher o SMTP."
