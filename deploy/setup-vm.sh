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
apt-get install -y -q git nginx snapd

# ── 2. Docker ─────────────────────────────────────────────────────────────────
log "2/7  Docker"
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
fi
# Adiciona usuário corrente ao grupo docker (aplica na próxima sessão)
usermod -aG docker "${SUDO_USER:-$USER}" 2>/dev/null || true

# ── 3. SSL (Let's Encrypt, certificado coringa via DNS-01/Cloudflare) ─────────
# Roda ANTES do nginx (passo 4): o certbot aqui não depende de nginx nem de
# porta 80 (valida por DNS, não HTTP), e o nginx.conf deste repo já referencia
# os arquivos do certificado — se o nginx fosse carregado primeiro, o
# `nginx -t` falharia por o certificado ainda não existir.
#
# certbot instalado via SNAP (não apt): o certbot do apt puxa pyOpenSSL/
# cryptography do sistema, que já quebrou 1x em produção com
# `AttributeError: module 'lib' has no attribute 'GEN_EMAIL'`. O snap roda
# isolado do Python do sistema e evita esse problema.
log "3/7  SSL — certbot (snap, plugin DNS Cloudflare — cobre wildcard)"
echo ""
echo "  ⚠️  IMPORTANTE: DNS já deve apontar taylorethedy.com e *.taylorethedy.com"
echo "  para o IP desta VM. Teste: dig +short taylorethedy.com"
echo ""
echo "  Pré-requisito manual (uma vez só): token de API da Cloudflare (escopo"
echo "  Zone:DNS:Edit, restrito à zona taylorethedy.com — não o Global API Key)"
echo "  salvo em /root/.secrets/certbot/cloudflare.ini (chmod 600). Não versionar."
echo ""
read -rp "  DNS propagado e arquivo de credenciais pronto? [s/N] " dns_ok
if [[ "${dns_ok,,}" != "s" ]]; then
  echo "  Configure DNS/token e rode manualmente depois:"
  echo "    snap install --classic certbot && ln -sf /snap/bin/certbot /usr/bin/certbot"
  echo "    snap install certbot-dns-cloudflare"
  echo "    snap set certbot trust-plugin-with-root=ok"
  echo "    snap connect certbot:plugin certbot-dns-cloudflare"
  echo "    certbot certonly --dns-cloudflare \\"
  echo "      --dns-cloudflare-credentials /root/.secrets/certbot/cloudflare.ini \\"
  echo "      -d taylorethedy.com -d '*.taylorethedy.com'"
  echo "  Continuando sem SSL por enquanto (o nginx do passo 4 vai falhar até o"
  echo "  certificado existir — rode este passo antes de tentar de novo)."
else
  snap install --classic certbot
  ln -sf /snap/bin/certbot /usr/bin/certbot
  snap install certbot-dns-cloudflare
  snap set certbot trust-plugin-with-root=ok
  snap connect certbot:plugin certbot-dns-cloudflare
  certbot certonly --dns-cloudflare \
    --dns-cloudflare-credentials /root/.secrets/certbot/cloudflare.ini \
    -d taylorethedy.com -d "*.taylorethedy.com"
  # Renovação automática via timer do snap (snap.certbot.renew.timer) — já
  # habilitado por padrão pela instalação do snap, sem passo extra aqui.
fi

# ── 4. Nginx ──────────────────────────────────────────────────────────────────
log "4/7  Nginx"
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/barbeariapro
ln -sf /etc/nginx/sites-available/barbeariapro /etc/nginx/sites-enabled/barbeariapro
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx

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
echo "  Frontend : https://taylorethedy.com (+ subdomínio por barbearia-cliente)"
echo "  API      : https://api.taylorethedy.com"
echo "  API Docs : https://api.taylorethedy.com/docs"
echo ""
echo "  Logs:  docker compose -f docker-compose.app.yml logs -f"
echo "  Status: docker compose -f docker-compose.app.yml ps"
echo ""
echo "⚠️  Lembrete pós-deploy:"
echo "  1. Adicione https://api.taylorethedy.com/integracoes/google/calendar/callback"
echo "     no Google Cloud Console → OAuth 2.0 Client IDs."
echo "  2. Importe os workflows n8n via:"
echo "     docker compose cp workflows.json n8n:/tmp/"
echo "     docker compose exec n8n n8n import:workflow --input=/tmp/workflows.json"
