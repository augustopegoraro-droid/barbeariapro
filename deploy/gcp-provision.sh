#!/usr/bin/env bash
# BarbeariaPro — Provisiona infraestrutura GCP
# Executar UMA VEZ na máquina LOCAL com gcloud autenticado.
#
# Pré-requisitos:
#   gcloud auth login
#   gcloud config set project barberiapro-app
set -euo pipefail

PROJECT=barberiapro-app
ZONE=southamerica-east1-a
REGION=southamerica-east1
INSTANCE=barbeariapro
MACHINE=e2-standard-2   # 2 vCPU / 8 GB — comporta postgres+n8n+evolution+app
DISK_GB=50

echo "━━━ 1/4  IP estático ━━━"
if gcloud compute addresses describe barbeariapro-ip \
      --project="$PROJECT" --region="$REGION" &>/dev/null; then
  echo "  IP já reservado — pulando."
else
  gcloud compute addresses create barbeariapro-ip \
    --project="$PROJECT" --region="$REGION"
fi

STATIC_IP=$(gcloud compute addresses describe barbeariapro-ip \
              --project="$PROJECT" --region="$REGION" \
              --format="value(address)")
echo "  IP: $STATIC_IP"

echo "━━━ 2/4  VM ($MACHINE) ━━━"
if gcloud compute instances describe "$INSTANCE" \
      --project="$PROJECT" --zone="$ZONE" &>/dev/null; then
  echo "  VM já existe — pulando criação."
else
  gcloud compute instances create "$INSTANCE" \
    --project="$PROJECT" \
    --zone="$ZONE" \
    --machine-type="$MACHINE" \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size="${DISK_GB}GB" \
    --boot-disk-type=pd-balanced \
    --address="$STATIC_IP" \
    --tags=http-server,https-server
fi

echo "━━━ 3/4  Regras de firewall ━━━"
gcloud compute firewall-rules create allow-http \
  --project="$PROJECT" --allow=tcp:80 \
  --target-tags=http-server --description="HTTP Nginx" \
  2>/dev/null || echo "  Regra HTTP já existe."

gcloud compute firewall-rules create allow-https \
  --project="$PROJECT" --allow=tcp:443 \
  --target-tags=https-server --description="HTTPS Nginx" \
  2>/dev/null || echo "  Regra HTTPS já existe."

echo "━━━ 4/4  Próximos passos ━━━"
cat <<EOF

✅ Infraestrutura pronta — IP: $STATIC_IP

Agora configure o DNS (no seu provedor de domínio):
  app.taylorethedy.com.br  →  A  →  $STATIC_IP
  api.taylorethedy.com.br  →  A  →  $STATIC_IP

Aguarde a propagação (~5–30 min) e então:

  gcloud compute ssh $INSTANCE \\
    --project=$PROJECT --zone=$ZONE

  Dentro da VM:
    git clone https://github.com/augustopegoraro-droid/barbeariapro.git /opt/barbeariapro
    cd /opt/barbeariapro
    cp .env.production.example .env && nano .env
    cp .env.docker.example .env.docker && nano .env.docker
    bash deploy/setup-vm.sh
EOF
