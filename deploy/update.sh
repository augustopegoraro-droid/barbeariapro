#!/usr/bin/env bash
# BarbeariaPro — Atualização de produção (zero-downtime)
# Executar na VM após cada push para main.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "→ Pull origin/main..."
git pull origin main

echo "→ Migrations (se houver novas)..."
# NÃO usar `source .env` aqui: o arquivo é KEY=VALUE de produção, não um script
# bash válido (valores como CORS_ORIGIN_REGEX têm parênteses/`?` não-escapados
# que quebram o parser do source). Extrai só a linha necessária.
ADMIN_DATABASE_URL="$(grep '^ADMIN_DATABASE_URL=' .env | tail -n1 | cut -d= -f2-)"
if [ -z "$ADMIN_DATABASE_URL" ]; then
  echo "❌ ADMIN_DATABASE_URL não definido em .env — abortando." >&2
  exit 1
fi
docker build -f Dockerfile.migrate -t barbeariapro-migrate . -q
docker run --rm \
  --env DATABASE_URL="$ADMIN_DATABASE_URL" \
  --add-host=host.docker.internal:host-gateway \
  barbeariapro-migrate

echo "→ Rebuild e restart do app..."
docker compose -f docker-compose.app.yml up -d --build

echo "✅ Atualização concluída."
docker compose -f docker-compose.app.yml ps
