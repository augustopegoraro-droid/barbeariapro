#!/usr/bin/env bash
# BarbeariaPro — Setup inicial da VM GCP
# Executar UMA VEZ dentro da VM após clonar o repositório.
#
# Pré-requisito: .env e .env.docker já preenchidos a partir dos exemplos.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

log() { echo "━━━ $* ━━━"; }

# ── 1. Pacotes do sistema ──────────────────────────────────────────────────────
log "1/7  Pacotes do sistema"
apt-get update -y -q
apt-get install -y -q git nginx certbot python3-certbot-nginx

# ── 2. Docker ─────────────────────────────────────────────────────────────────
log "2/7  Docker"
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
fi
# Adiciona usuário corrente ao grupo docker (aplica na próxima sessão)
usermod -aG docker "${SUDO_USER:-$USER}" 2>/dev/null || true

# ── 3. Nginx ──────────────────────────────────────────────────────────────────
log "3/7  Nginx"
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/barbeariapro
ln -sf /etc/nginx/sites-available/barbeariapro /etc/nginx/sites-enabled/barbeariapro
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx

# ── 4. SSL (Let's Encrypt) ────────────────────────────────────────────────────
log "4/7  SSL — certbot"
echo ""
echo "  ⚠️  IMPORTANTE: verifique que os DNS já propagaram antes de continuar."
echo "  app.taylorethedy.com.br e api.taylorethedy.com.br devem apontar para este IP."
echo "  Teste: dig +short app.taylorethedy.com.br"
echo ""
read -rp "  DNS OK? [s/N] " dns_ok
if [[ "${dns_ok,,}" != "s" ]]; then
  echo "  Configure o DNS e re-execute a partir deste passo:"
  echo "    certbot --nginx -d app.taylorethedy.com.br -d api.taylorethedy.com.br --redirect --agree-tos --no-eff-email"
  echo "  Continuando sem SSL por enquanto..."
else
  certbot --nginx \
    -d app.taylorethedy.com.br \
    -d api.taylorethedy.com.br \
    --redirect --agree-tos --no-eff-email
  # Renovação automática via cron já configurada pelo certbot
fi

# ── 5. Infra (PostgreSQL + n8n + Evolution) ───────────────────────────────────
log "5/7  Infra (postgres / n8n / evolution)"
docker compose up -d

echo "  Aguardando PostgreSQL ficar pronto..."
until docker exec barbeariapro-postgres pg_isready -U postgres -q; do
  sleep 2
done
echo "  PostgreSQL OK."

# ── 6. Migrations ─────────────────────────────────────────────────────────────
log "6/7  Migrations Alembic"
set -a; source .env; set +a

# Constrói e roda imagem de migration (Dockerfile.migrate)
docker build -f Dockerfile.migrate -t barbeariapro-migrate . -q
docker run --rm \
  --env DATABASE_URL="$ADMIN_DATABASE_URL" \
  --add-host=host.docker.internal:host-gateway \
  barbeariapro-migrate

# ── 7. App (Backend + Frontend) ───────────────────────────────────────────────
log "7/7  App (backend + frontend)"
docker compose -f docker-compose.app.yml up -d --build

echo ""
echo "✅ Deploy concluído!"
echo ""
echo "  Frontend : https://app.taylorethedy.com.br"
echo "  API      : https://api.taylorethedy.com.br"
echo "  API Docs : https://api.taylorethedy.com.br/docs"
echo ""
echo "  Logs:  docker compose -f docker-compose.app.yml logs -f"
echo "  Status: docker compose -f docker-compose.app.yml ps"
echo ""
echo "⚠️  Lembrete pós-deploy:"
echo "  1. Adicione https://api.taylorethedy.com.br/integracoes/google/calendar/callback"
echo "     no Google Cloud Console → OAuth 2.0 Client IDs."
echo "  2. Importe os workflows n8n via:"
echo "     docker compose cp workflows.json n8n:/tmp/"
echo "     docker compose exec n8n n8n import:workflow --input=/tmp/workflows.json"
