#!/usr/bin/env bash
# BarbeariaPro — Atualização de produção (zero-downtime)
# Executar na VM após cada push para main.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "→ Pull origin/main..."
git pull origin main

echo "→ Migrations (se houver novas)..."
set -a; source .env; set +a
docker build -f Dockerfile.migrate -t barbeariapro-migrate . -q
docker run --rm \
  --env DATABASE_URL="$ADMIN_DATABASE_URL" \
  --add-host=host.docker.internal:host-gateway \
  barbeariapro-migrate

echo "→ Rebuild e restart do app..."
docker compose -f docker-compose.app.yml up -d --build

echo "✅ Atualização concluída."
docker compose -f docker-compose.app.yml ps
