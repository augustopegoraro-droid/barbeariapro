#!/usr/bin/env bash
# BarbeariaPro — Deploy completo no Google Cloud (Cloud Run + Cloud SQL)
# Executar na máquina LOCAL. Não requer SSH na VM para o app.
#
# O que este script faz automaticamente:
#   1. Habilita as APIs GCP necessárias
#   2. Cria repositório de imagens (Artifact Registry)
#   3. Faz build e push das imagens Docker (backend + frontend)
#   4. Cria banco PostgreSQL gerenciado (Cloud SQL)
#   5. Migra os dados do banco local para o Cloud SQL
#   6. Cria e armazena todas as senhas no Secret Manager
#   7. Faz deploy do backend no Cloud Run (HTTPS automático)
#   8. Roda as migrations Alembic
#   9. Faz deploy do frontend no Cloud Run (HTTPS automático)
#  10. Cria zona DNS no Cloud DNS
#  11. Configura Evolution + n8n na VM via SSH automaticamente
#
# Você só precisa:
#   - Responder 3 perguntas sobre suas chaves (Evolution, OpenAI, Google)
#   - Atualizar os nameservers no site onde registrou o domínio (eu mostro os valores)

set -euo pipefail

# ── Constantes ────────────────────────────────────────────────────────────────
PROJECT=barberiapro-app
REGION=southamerica-east1
ZONE="${REGION}-a"
VM_INSTANCE=barbeariapro
VM_IP=34.95.199.134

APP_DOMAIN=taylorethedy.app          # frontend
API_DOMAIN=api.taylorethedy.com      # backend

REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/barbeariapro"
SQL_INSTANCE=barbeariapro-db
APP_DB=barbeariapro
APP_USER=barber_app
OWNER_USER=barber_owner
DNS_ZONE_APP=taylorethedy-app-zone   # zona para taylorethedy.app
DNS_ZONE_COM=taylorethedy-com-zone   # zona para taylorethedy.com (api.taylorethedy.com)
SA_NAME=barbeariapro-run
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
BACKUP_BUCKET="${PROJECT}-backups"
GOOGLE_CLIENT_ID=6349897322-9sm7kq2fu81d6rqec2hnv4toucesvc6g.apps.googleusercontent.com

log()  { echo ""; echo "━━━ $* ━━━"; }
ok()   { echo "  ✓ $*"; }
warn() { echo "  ⚠️  $*"; }

# ── 0. Coletar segredos antes de começar ─────────────────────────────────────
log "0/11  Segredos necessários"
echo ""
echo "  Precisamos de 3 valores que só você tem."
echo "  Os demais são gerados automaticamente."
echo ""

read -rsp "  EVOLUTION_API_KEY (chave da Evolution API, ver .env atual): " EVOLUTION_API_KEY
echo ""
read -rsp "  OPENAI_API_KEY (chave da OpenAI, ver .env atual): " OPENAI_API_KEY
echo ""
read -rsp "  GOOGLE_CLIENT_SECRET (Google Cloud Console → OAuth 2.0): " GOOGLE_CLIENT_SECRET
echo ""

# Gerar segredos automaticamente
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
TOKEN_ENC_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
  || python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
AUTH_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(48))")
BOT_API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
APP_PWD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
OWNER_PWD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
EVOLUTION_PG_PWD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")

ok "Segredos coletados."

# ── 1. APIs GCP ───────────────────────────────────────────────────────────────
log "1/11  Habilitando APIs do GCP"
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  dns.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  --project="$PROJECT" --quiet
ok "APIs habilitadas."

# ── 2. Artifact Registry ──────────────────────────────────────────────────────
log "2/11  Artifact Registry"
gcloud artifacts repositories create barbeariapro \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT" \
  --description="Imagens BarbeariaPro" \
  2>/dev/null && ok "Repositório criado." || ok "Repositório já existe."

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
ok "Docker autenticado no Artifact Registry."

# ── 3. Build e push das imagens ───────────────────────────────────────────────
log "3/11  Build e push Docker"
echo "  → Backend..."
docker build -t "${REGISTRY}/backend:latest" . -q
docker push "${REGISTRY}/backend:latest" -q
ok "Backend enviado."

echo "  → Imagem de migrations..."
docker build -f Dockerfile.migrate -t "${REGISTRY}/migrate:latest" . -q
docker push "${REGISTRY}/migrate:latest" -q
ok "Migrate enviado."

echo "  → Frontend (API: https://${API_DOMAIN})..."
docker build \
  --build-arg NEXT_PUBLIC_API_URL="https://${API_DOMAIN}" \
  --build-arg NEXT_PUBLIC_ORG_ID="3" \
  -t "${REGISTRY}/frontend:latest" \
  ./barbearia-frontend -q
docker push "${REGISTRY}/frontend:latest" -q
ok "Frontend enviado."

# ── 4. Cloud SQL ──────────────────────────────────────────────────────────────
log "4/11  Cloud SQL (PostgreSQL 16)"
if gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT" &>/dev/null; then
  ok "Instância já existe."
else
  echo "  Criando instância (~5 minutos)..."
  gcloud sql instances create "$SQL_INSTANCE" \
    --database-version=POSTGRES_16 \
    --tier=db-f1-micro \
    --region="$REGION" \
    --storage-size=10GB \
    --storage-auto-increase \
    --no-assign-ip \
    --enable-google-private-path \
    --project="$PROJECT"
  ok "Instância criada."
fi

# Habilitar IP público (necessário para import de backup via gcloud)
gcloud sql instances patch "$SQL_INSTANCE" \
  --assign-ip --project="$PROJECT" --quiet 2>/dev/null || true

gcloud sql users set-password postgres \
  --instance="$SQL_INSTANCE" \
  --password="$APP_PWD" \
  --project="$PROJECT" --quiet

gcloud sql databases create "$APP_DB" \
  --instance="$SQL_INSTANCE" --project="$PROJECT" \
  2>/dev/null && ok "Database criado." || ok "Database já existe."

gcloud sql users create "$APP_USER" \
  --instance="$SQL_INSTANCE" --password="$APP_PWD" \
  --project="$PROJECT" 2>/dev/null || \
gcloud sql users set-password "$APP_USER" \
  --instance="$SQL_INSTANCE" --password="$APP_PWD" \
  --project="$PROJECT" --quiet
ok "Usuário $APP_USER configurado."

gcloud sql users create "$OWNER_USER" \
  --instance="$SQL_INSTANCE" --password="$OWNER_PWD" \
  --project="$PROJECT" 2>/dev/null || \
gcloud sql users set-password "$OWNER_USER" \
  --instance="$SQL_INSTANCE" --password="$OWNER_PWD" \
  --project="$PROJECT" --quiet
ok "Usuário $OWNER_USER configurado."

SQL_CONN="${PROJECT}:${REGION}:${SQL_INSTANCE}"
DB_URL="postgresql+psycopg://${APP_USER}:${APP_PWD}@/${APP_DB}?host=/cloudsql/${SQL_CONN}"
ADMIN_DB_URL="postgresql+psycopg://${OWNER_USER}:${OWNER_PWD}@/${APP_DB}?host=/cloudsql/${SQL_CONN}"

# ── 5. Migração de dados do banco local ───────────────────────────────────────
log "5/11  Migração de dados (banco local → Cloud SQL)"
SQL_PUBLIC_IP=$(gcloud sql instances describe "$SQL_INSTANCE" \
  --project="$PROJECT" --format="value(ipAddresses[0].ipAddress)")

if docker ps --format '{{.Names}}' | grep -q "^barbeariapro-postgres$"; then
  echo "  Fazendo dump do banco local..."
  docker exec barbeariapro-postgres \
    pg_dump -U postgres barbeariapro \
    --no-owner --no-acl -Fc \
    > /tmp/barbeariapro_backup.dump

  gsutil mb -p "$PROJECT" -l "$REGION" "gs://${BACKUP_BUCKET}" 2>/dev/null || true
  gsutil cp /tmp/barbeariapro_backup.dump "gs://${BACKUP_BUCKET}/barbeariapro_backup.dump"
  ok "Backup enviado para gs://${BACKUP_BUCKET}/."

  # Autorizar o Cloud SQL a acessar o bucket
  SQL_SA=$(gcloud sql instances describe "$SQL_INSTANCE" \
    --project="$PROJECT" --format="value(serviceAccountEmailAddress)")
  gsutil iam ch "serviceAccount:${SQL_SA}:roles/storage.objectViewer" \
    "gs://${BACKUP_BUCKET}" 2>/dev/null || true

  echo "  Importando para Cloud SQL (aguarde)..."
  gcloud sql import bq "$SQL_INSTANCE" \
    "gs://${BACKUP_BUCKET}/barbeariapro_backup.dump" \
    --database="$APP_DB" \
    --project="$PROJECT" \
    --quiet 2>/dev/null || \
  warn "Import automático falhou (formato). As migrations vão criar o schema do zero."
  rm -f /tmp/barbeariapro_backup.dump
else
  warn "Container barbeariapro-postgres não está rodando. Pulando migração de dados."
  warn "O banco Cloud SQL será inicializado do zero pelas migrations."
fi

# ── 6. Service Account ────────────────────────────────────────────────────────
log "6/11  Service Account"
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="BarbeariaPro Cloud Run" \
  --project="$PROJECT" \
  2>/dev/null && ok "Service account criada." || ok "Service account já existe."

for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$role" --quiet 2>/dev/null || true
done
ok "Permissões configuradas."

# ── 7. Secret Manager ─────────────────────────────────────────────────────────
log "7/11  Secret Manager"
_secret() {
  local name="$1" value="$2"
  if gcloud secrets describe "$name" --project="$PROJECT" &>/dev/null; then
    printf '%s' "$value" | gcloud secrets versions add "$name" \
      --data-file=- --project="$PROJECT" >/dev/null
  else
    printf '%s' "$value" | gcloud secrets create "$name" \
      --data-file=- --replication-policy=automatic --project="$PROJECT" >/dev/null
  fi
  ok "$name"
}

_secret DATABASE_URL         "$DB_URL"
_secret ADMIN_DATABASE_URL   "$ADMIN_DB_URL"
_secret SECRET_KEY           "$SECRET_KEY"
_secret TOKEN_ENCRYPTION_KEY "$TOKEN_ENC_KEY"
_secret AUTH_SECRET          "$AUTH_SECRET"
_secret BOT_API_KEY          "$BOT_API_KEY"
_secret EVOLUTION_API_KEY    "$EVOLUTION_API_KEY"
_secret OPENAI_API_KEY       "$OPENAI_API_KEY"
_secret GOOGLE_CLIENT_SECRET "$GOOGLE_CLIENT_SECRET"

# ── 8. Deploy backend ─────────────────────────────────────────────────────────
log "8/11  Cloud Run — Backend"
gcloud run deploy barbeariapro-backend \
  --image="${REGISTRY}/backend:latest" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --service-account="$SA_EMAIL" \
  --add-cloudsql-instances="$SQL_CONN" \
  --set-secrets="\
DATABASE_URL=DATABASE_URL:latest,\
SECRET_KEY=SECRET_KEY:latest,\
BOT_API_KEY=BOT_API_KEY:latest,\
EVOLUTION_API_KEY=EVOLUTION_API_KEY:latest,\
OPENAI_API_KEY=OPENAI_API_KEY:latest,\
GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest,\
TOKEN_ENCRYPTION_KEY=TOKEN_ENCRYPTION_KEY:latest" \
  --set-env-vars="\
BOT_ORGANIZATION_ID=3,\
BOT_UNIT_ID=1,\
EVOLUTION_API_URL=http://${VM_IP}:8080,\
EVOLUTION_INSTANCE_NAME=barbearia_instance,\
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},\
GOOGLE_REDIRECT_URI=https://${API_DOMAIN}/integracoes/google/calendar/callback,\
GOOGLE_FRONTEND_SUCCESS_URL=https://${APP_DOMAIN}/admin/configuracoes,\
CORS_ORIGINS=https://${APP_DOMAIN},\
ENABLE_DEBUG_ENDPOINTS=false" \
  --min-instances=1 \
  --memory=512Mi \
  --project="$PROJECT" \
  --quiet

BACKEND_URL=$(gcloud run services describe barbeariapro-backend \
  --region="$REGION" --project="$PROJECT" \
  --format="value(status.url)")
ok "Backend: $BACKEND_URL"

# ── 8b. Migrations ────────────────────────────────────────────────────────────
log "8b. Migrations Alembic (Cloud Run Job)"
gcloud run jobs create barbeariapro-migrate \
  --image="${REGISTRY}/migrate:latest" \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --add-cloudsql-instances="$SQL_CONN" \
  --set-secrets="DATABASE_URL=ADMIN_DATABASE_URL:latest" \
  --project="$PROJECT" \
  2>/dev/null || \
gcloud run jobs update barbeariapro-migrate \
  --image="${REGISTRY}/migrate:latest" \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --add-cloudsql-instances="$SQL_CONN" \
  --set-secrets="DATABASE_URL=ADMIN_DATABASE_URL:latest" \
  --project="$PROJECT"

echo "  Executando migrations..."
gcloud run jobs execute barbeariapro-migrate \
  --region="$REGION" --project="$PROJECT" --wait
ok "Migrations aplicadas."

# ── 9. Deploy frontend ────────────────────────────────────────────────────────
log "9/11  Cloud Run — Frontend"
gcloud run deploy barbeariapro-frontend \
  --image="${REGISTRY}/frontend:latest" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --service-account="$SA_EMAIL" \
  --set-secrets="AUTH_SECRET=AUTH_SECRET:latest" \
  --set-env-vars="\
API_URL_INTERNAL=${BACKEND_URL},\
AUTH_TRUST_HOST=true,\
NEXT_PUBLIC_ORG_ID=3" \
  --min-instances=1 \
  --memory=512Mi \
  --project="$PROJECT" \
  --quiet

FRONTEND_URL=$(gcloud run services describe barbeariapro-frontend \
  --region="$REGION" --project="$PROJECT" \
  --format="value(status.url)")
ok "Frontend: $FRONTEND_URL"

# ── 10. Cloud DNS — duas zonas separadas ─────────────────────────────────────
log "10/11  Cloud DNS (taylorethedy.app + taylorethedy.com)"

# Zona para taylorethedy.app (frontend)
gcloud dns managed-zones create "$DNS_ZONE_APP" \
  --dns-name="taylorethedy.app." \
  --description="Frontend BarbeariaPro" \
  --project="$PROJECT" \
  2>/dev/null && ok "Zona taylorethedy.app criada." || ok "Zona taylorethedy.app já existe."

# Zona para taylorethedy.com (API — api.taylorethedy.com)
gcloud dns managed-zones create "$DNS_ZONE_COM" \
  --dns-name="taylorethedy.com." \
  --description="API BarbeariaPro" \
  --project="$PROJECT" \
  2>/dev/null && ok "Zona taylorethedy.com criada." || ok "Zona taylorethedy.com já existe."

# Mapear domínios ao Cloud Run (Google gerencia SSL automaticamente)
gcloud run domain-mappings create \
  --service=barbeariapro-frontend \
  --domain="$APP_DOMAIN" \
  --region="$REGION" \
  --project="$PROJECT" \
  2>/dev/null || ok "Mapeamento frontend já existe."

gcloud run domain-mappings create \
  --service=barbeariapro-backend \
  --domain="$API_DOMAIN" \
  --region="$REGION" \
  --project="$PROJECT" \
  2>/dev/null || ok "Mapeamento api já existe."

# Adicionar registros DNS gerados pelo Cloud Run nas suas respectivas zonas
echo "  Coletando registros DNS do Cloud Run..."
sleep 5

_add_dns_records() {
  local domain="$1" zone="$2" root_fqdn="$3"
  gcloud run domain-mappings describe \
    --domain="$domain" --region="$REGION" --project="$PROJECT" \
    --format="json(status.resourceRecords)" 2>/dev/null \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
records = data.get('status', {}).get('resourceRecords', [])
for r in records:
    print(r.get('type',''), r.get('name','@'), r.get('rrdata',''))
" | while read -r rtype rname rdata; do
    [ -z "$rtype" ] && continue
    FQDN="${rname}.${root_fqdn}."
    [ "$rname" = "@" ] && FQDN="${root_fqdn}."
    gcloud dns record-sets create "$FQDN" \
      --zone="$zone" --type="$rtype" --ttl=300 \
      --rrdatas="$rdata" --project="$PROJECT" \
      2>/dev/null || true
  done
}

_add_dns_records "$APP_DOMAIN" "$DNS_ZONE_APP" "taylorethedy.app"
_add_dns_records "$API_DOMAIN" "$DNS_ZONE_COM" "taylorethedy.com"
ok "Registros DNS configurados nas duas zonas."

# ── 11. VM — Evolution + n8n ──────────────────────────────────────────────────
log "11/11  VM — Evolution API + n8n"

# Abrir porta 8080 para Evolution (protegida por API key)
gcloud compute firewall-rules create allow-evolution \
  --project="$PROJECT" \
  --allow=tcp:8080 \
  --target-tags=http-server \
  --description="Evolution API (autenticada por API key)" \
  2>/dev/null && ok "Porta 8080 aberta." || ok "Porta 8080 já estava aberta."

# Abrir porta 5678 para n8n (acesso admin — fechar após configurar)
gcloud compute firewall-rules create allow-n8n \
  --project="$PROJECT" \
  --allow=tcp:5678 \
  --target-tags=http-server \
  --description="n8n UI (temporário para setup inicial)" \
  2>/dev/null && ok "Porta 5678 aberta." || ok "Porta 5678 já estava aberta."

echo "  Configurando VM via SSH (pode pedir confirmação da chave SSH)..."
gcloud compute ssh "$VM_INSTANCE" \
  --project="$PROJECT" \
  --zone="$ZONE" \
  --command="
set -e
# Docker
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh -s -- -q
  systemctl enable docker --quiet
  systemctl start docker
fi

# Repositório
if [ ! -d /opt/barbeariapro ]; then
  git clone https://github.com/augustopegoraro-droid/barbeariapro.git /opt/barbeariapro
else
  git -C /opt/barbeariapro pull origin main
fi

# .env mínimo para infra (sem postgres — está no Cloud SQL)
cat > /opt/barbeariapro/.env <<'ENVEOF'
BOT_API_KEY=${BOT_API_KEY}
EVOLUTION_API_KEY=${EVOLUTION_API_KEY}
EVOLUTION_POSTGRES_PASSWORD=${EVOLUTION_PG_PWD}
EVOLUTION_SERVER_URL=http://${VM_IP}:8080
OPENAI_API_KEY=${OPENAI_API_KEY}
POSTGRES_USER=postgres
POSTGRES_PASSWORD=nao-usado-vm
POSTGRES_DB=barbeariapro
GENERIC_TIMEZONE=America/Sao_Paulo
TZ=America/Sao_Paulo
ENVEOF

cd /opt/barbeariapro

# Subir apenas Evolution + n8n (postgres fica no Cloud SQL)
docker compose up -d n8n evolution-postgres evolution-redis evolution-api

echo 'Containers iniciados na VM:'
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
"
ok "Evolution + n8n configurados na VM."

# ── Resumo final ──────────────────────────────────────────────────────────────
NS_APP=$(gcloud dns managed-zones describe "$DNS_ZONE_APP" \
  --project="$PROJECT" --format="value(nameServers)" | tr ';' '\n' | sed 's/^/    /')
NS_COM=$(gcloud dns managed-zones describe "$DNS_ZONE_COM" \
  --project="$PROJECT" --format="value(nameServers)" | tr ';' '\n' | sed 's/^/    /')

cat <<SUMMARY

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅  DEPLOY CONCLUÍDO

  URLs já funcionam (certificado SSL leva ~15 min):
    Frontend : $FRONTEND_URL
    Backend  : $BACKEND_URL

  URLs finais (após DNS propagar):
    https://$APP_DOMAIN
    https://$API_DOMAIN

━━━  AÇÃO NECESSÁRIA 1/3: Nameservers de taylorethedy.app  ━━━━

  No site onde registrou taylorethedy.app (GoDaddy, Namecheap etc.),
  substitua os nameservers por estes 4:

$NS_APP

━━━  AÇÃO NECESSÁRIA 2/3: Nameservers de taylorethedy.com  ━━━━

  No site onde registrou taylorethedy.com,
  substitua os nameservers por estes 4:

$NS_COM

  Após salvar os dois, aguarde ~30 minutos para propagar.

━━━  AÇÃO NECESSÁRIA 3/3: Google Cloud Console (OAuth)  ━━━━━━━

  console.cloud.google.com → APIs → Credenciais → OAuth 2.0
  Adicione URI de redirect autorizado:
    https://$API_DOMAIN/integracoes/google/calendar/callback

━━━  n8n — importar workflow (após DNS propagar)  ━━━━━━━━━━━━━

  Acesse http://$VM_IP:5678 e importe workflows.json.
  Depois feche a porta 5678:
    gcloud compute firewall-rules delete allow-n8n --project=$PROJECT

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUMMARY
