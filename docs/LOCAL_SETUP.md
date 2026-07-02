# Rodar o BarbeariaPro localmente (Mac M1 / sem GCP)

Guia para rodar a stack no seu Mac (Apple Silicon) via Docker Desktop, independente
do Google Cloud. Serve para dev/teste e para as **primeiras organizações**.

> **Sobre confiabilidade:** um laptop dorme, reinicia e usa IP residencial dinâmico.
> Para clientes reais dependerem da agenda 24/7, o ideal (ainda fora do Google) é um
> **VPS barato sempre-ligado** (Hetzner/DigitalOcean ~€4-6/mês). A migração é idêntica
> à local — só troca a máquina. Use o Mac para dev e um VPS para produção quando escalar.

## 0. Recuperar os dados de produção (fazer ANTES)

Os 2.913 clientes + 47 agendamentos importados vivem no Postgres da VM do GCP. Duas
situações:

- **Ainda acesso o Google/gcloud:** só reautenticar e baixar o dump — **prioridade**.
  ```bash
  gcloud auth login
  gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a \
    --command "sudo docker exec barbeariapro-postgres pg_dump -U postgres -d barbeariapro" > prod_dump.sql
  ```
- **Perdi a conta de vez:** a **Trinks é a fonte** — re-exporte clientes/agendamentos/
  débitos/ranking e reconstrua com os importadores (`scripts/import_trinks*.py`). Perde-se
  só o criado dentro do sistema depois do import (pouco, início).

## 1. Qual "migração" (Alembic) rodar

- **Banco local novo (vazio):** `alembic upgrade head` cria todo o schema até
  **`0023_client_debts`** (o `setup_local.sh` já faz isso).
- **Restaurando o dump da VM:** o dump está em **`0022`** (a `0023` de débitos nunca foi
  aplicada em prod). Depois de restaurar, rode `alembic upgrade head` para aplicar a `0023`.

## 2. Pré-requisitos

- **Docker Desktop for Mac (Apple Silicon)** rodando.
- `.venv` com as deps (o mesmo dos testes): `python -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- Arquivos de env:
  ```bash
  cp .env.example .env                 # preencha SECRET_KEY (openssl rand -hex 32) e afins
  cp .env.docker.example .env.docker   # DATABASE_URL já aponta p/ host.docker.internal:5432
  ```
  Em `.env`, para local, use `NEXT_PUBLIC_API_URL=http://localhost:8000` e
  `CORS_ORIGINS=http://localhost:3000`.

## 3. Subir o banco + schema (um comando)

```bash
bash scripts/setup_local.sh
```
Isso: sobe o Postgres (container `barbeariapro-postgres` :5432), cria a role `barber_app`
(RLS, senha `senha123`), roda as migrations até `0023` e concede os privilégios.

## 4. Popular dados

Escolha um:
```bash
# (a) restaurar o dump de produção
docker exec -i barbeariapro-postgres psql -U postgres -d barbeariapro < prod_dump.sql
# depois, se o dump for 0022:
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/barbeariapro" .venv/bin/python -m alembic upgrade head

# (b) seed de exemplo
ADMIN_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/barbeariapro" \
  .venv/bin/python scripts/seed.py

# (c) re-importar da Trinks (org já existente)
.venv/bin/python scripts/import_trinks.py --org-id 1 --file <clientes.csv> --commit
.venv/bin/python scripts/import_trinks_appointments.py --org-id 1 --file <agenda.csv> --commit
.venv/bin/python scripts/enrich_trinks_ranking.py --org-id 1 --file <ranking.csv> --commit
.venv/bin/python scripts/import_trinks_debts.py --org-id 1 --file <debitos_LIMPO.csv> --commit
```

## 5. Subir a aplicação

```bash
docker compose -f docker-compose.app.yml up -d --build backend frontend
```
- Backend: http://localhost:8000/health
- Frontend: http://localhost:3000

## 6. WhatsApp / n8n (opcional, por ora)

`n8n` e `evolution` estão no `docker-compose.yml`, mas o WhatsApp precisa de **webhook
público** (WhatsApp → seu servidor), o que não funciona direto atrás do NAT de casa.
Opções: um **túnel** (`cloudflared`/`ngrok`) apontando para `localhost`, ou deixar o bot
desligado nos testes (a trava do `whatsapp.py` já não envia sem `EVOLUTION_API_URL`).
A direção de médio prazo continua Chatwoot + WhatsApp Cloud API (D-49).

## Resumo do que muda vs. GCP
- **Host:** VM do GCP → Docker Desktop no Mac (ou VPS). Mesmos containers/compose.
- **URLs:** `34.95.199.134` → `localhost`. Ajustar `.env` (NEXT_PUBLIC_API_URL, CORS_ORIGINS).
- **DDL/migrations:** superuser `postgres` local (não há `ADMIN_DATABASE_URL` na VM; local usa `postgres:postgres`).
- **Dados:** dump do GCP (se recuperável) ou re-export da Trinks.
