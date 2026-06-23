# PROJECT_CONTEXT.md
> Fonte de verdade para novas sessões de desenvolvimento.
> Verificado contra o código E contra a VM de produção em **2026-06-23**.

---

## 0. LEIA PRIMEIRO — o que mudou em 2026-06-23

1. **A VM de produção foi encontrada ZERADA e reconstruída do zero nesta data.**
   Todos os containers, volumes e o pareamento WhatsApp anterior foram perdidos.
   A stack inteira foi remontada manualmente na VM (ver §4).
2. **A Fase 2 (Google Calendar) já foi mergeada em `main`** (commit `1773b30`).
   O branch `feat/fase2-google-calendar` não é mais o ativo — estamos em `main`.
3. **Produção roda no próprio VM via docker-compose, NÃO no Cloud Run.**
   O `deploy/gcp-cloud-run.sh` existe mas nunca rodou com sucesso (ver D-13).
4. **A produção restaurada usa `organization_id = 1`** (não org 3, como diziam os
   docs antigos). Banco re-semeado do zero. Ver §9.
5. **O bot WhatsApp está funcionando end-to-end** (conversa + agendamento). Ver §12.

---

## 1. O que é o projeto

**BarbeariaPro** — plataforma SaaS de gestão para barbearias e salões.
Cliente âncora em produção: **Barbearia Taylor & Thedy** (Palmas/TO), clientes reais.
Objetivo comercial: vender para mais barbearias; concorre com Trinks
(análise em `ROADMAP_IMPLEMENTACAO.md`).

---

## 2. Repositórios e estrutura de arquivos

| Repo / Diretório | Branch | Conteúdo |
|---|---|---|
| `/Users/apleandro/dev/barbeariapro` | `main` | Backend FastAPI + infra Docker + workflows n8n |
| `/Users/apleandro/dev/barbeariapro/barbearia-frontend` | `main` | Frontend Next.js (repo git **separado** dentro do diretório) |

> **Atenção:** `barbearia-frontend/` é um sub-repositório git independente.
> Commits de backend e frontend são feitos separadamente
> (`git -C barbearia-frontend/ ...`). Ver D-08.

**Estado git do backend (2026-06-23):**
- Branch `main`, **3 commits à frente de `origin/main` (NÃO pushados)** — o kit de
  deploy (`99eaabb`, `c9297bb`, `876d841`). Um clone novo do GitHub não tem esses
  commits nem `Dockerfile.migrate`/`docker-compose.app.yml` atualizados.
- `workflows.json` tem modificações locais **não commitadas** (correções do bot —
  ver CURRENT_SPRINT.md).

---

## 3. Stack tecnológica

### Backend
- **Python 3.9**, FastAPI, SQLAlchemy async (psycopg3), Alembic
- **PostgreSQL 16** com Row Level Security (multi-tenant por `organization_id`)
- Auth: JWT Bearer (`app/core/security.py`) + header **`X-Bot-Token`** para o bot
  (`app/api/bot.py:109`, validado em `:112` contra `settings.bot_api_key`)
- Criptografia de tokens OAuth: Fernet (`app/core/crypto.py`)

### Frontend
- **Next.js** App Router (versão nova — leia `barbearia-frontend/AGENTS.md` antes de mexer)
- next-auth (sessão JWT), Tailwind CSS, Axios (`barbearia-frontend/lib/api.ts`)
- `useSearchParams()` exige `<Suspense>` boundary (senão quebra o build)

### Infraestrutura
- **Docker Compose** — dois arquivos:
  - `docker-compose.yml`: infra (Postgres prod `:5432`, n8n `:5678`, Evolution `:8080`,
    evolution-postgres, evolution-redis)
  - `docker-compose.app.yml`: app (backend `:8000`, frontend `:3000`)
- O `docker-compose.app.yml` usa `.env.docker` para sobrescrever `DATABASE_URL`,
  `EVOLUTION_API_URL`, `API_URL_INTERNAL` para `host.docker.internal`.

---

## 4. PRODUÇÃO REAL — VM GCP (origem da verdade operacional)

| Item | Valor |
|---|---|
| Projeto GCP | `barberiapro-app` |
| VM | `barbeariapro` |
| Zona | `southamerica-east1-a` |
| IP externo | `34.95.199.134` |
| Acesso SSH | `gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a` |
| App na VM | `/opt/barbeariapro` (clone do repo + `.env` + `.env.docker`) |

### Containers em produção (verificado 2026-06-23)

```
barbeariapro-app-backend    :8000   (healthy)   FastAPI
barbeariapro-app-frontend   :3000   (healthy)   Next.js
barbeariapro-postgres       :5432   (healthy)   Postgres do app
evolution_api               :8080               Evolution API v2.3.7
evolution_postgres          (interno)           Postgres da Evolution
evolution_redis             (interno)           Redis da Evolution
n8n                         :5678               n8n v2.27.3
```

### Acessos administrativos
- **n8n editor:** `http://34.95.199.134:5678` — login `admin@barbeariapro.com` / `Barbearia2026`
- **Evolution manager:** `http://34.95.199.134:8080/manager` — login com `EVOLUTION_API_KEY`
- **App frontend:** `http://34.95.199.134:3000`
- **App backend:** `http://34.95.199.134:8000`
- **Postgres (admin):** `docker exec barbeariapro-postgres psql -U postgres -d barbeariapro`
  (o superuser é `postgres`; **não existe** role `barber_owner` — só `barber_app`)

### Firewall (target-tag `http-server`)
`allow-evolution` (8080), `allow-n8n` (5678), `allow-backend` (8000), `allow-frontend` (3000).
> ⚠️ Todas as portas estão abertas ao mundo. HTTPS/domínio ainda NÃO configurado —
> o env ativo usa IP (`http://34.95.199.134:*`), não os domínios `taylorethedy.app`.

---

## 5. Ambientes

| Ambiente | Onde | Banco | Evolution/Bot |
|---|---|---|---|
| **Produção** | VM GCP `34.95.199.134` | `barbeariapro-postgres:5432` (org 1) | **ATIVO** — dispara WhatsApp real |
| **Staging** | local (Mac) | `barbeariapro-staging-postgres:5433` | **VAZIO** (dry-run) |
| **Dev local** | local (Mac) | `barbeariapro-postgres:5432` (local) | conforme `.env` |

> O Mac também roda containers locais (`barbeariapro-app-backend/frontend/postgres`
> + `barbeariapro-staging-postgres`). Não confundir com os da VM.

### Como subir staging (local, para testes)
```bash
docker start barbeariapro-staging-postgres
set -a; . ./.env.staging; set +a
export SEED_ORG_ID=1
.venv/bin/python -m uvicorn app.main:app --port 8001
.venv/bin/python -m pytest tests/ -q
```

### Regra de Ouro (inviolável) — ver D-01
- `EVOLUTION_API_URL` e `EVOLUTION_INSTANCE_NAME` **VAZIOS** em staging e dev local.
- `DATABASE_URL` de staging aponta para `:5433`, nunca `:5432`.
- Trava nativa: `app/services/whatsapp.py:17` (dry-run quando Evolution vazio).

---

## 6. Rotas da API (confirmadas no código)

| Prefixo | Arquivo | Auth |
|---|---|---|
| `/health` | `app/api/health.py` | público |
| `/auth` | `app/api/auth.py` | público (login) |
| `/bot` | `app/api/bot.py` | **`X-Bot-Token`** |
| `/loyalty`, `/internal/loyalty` | `app/api/loyalty.py` | JWT / Bot |
| `/internal/reminders` | `app/api/reminders.py` | Bot |
| `/agenda` | `app/api/agenda.py` | JWT |
| `/barbeiro` | `app/api/barbeiro.py` | JWT |
| `/financeiro` | `app/api/financeiro.py` | JWT |
| `/equipe` | `app/api/equipe.py` | JWT |
| `/clientes` | `app/api/clientes.py` | JWT |
| `/dashboard`, `/dashboard/operacional` | `app/api/dashboard.py` | JWT |
| `/servicos` | `app/api/servicos.py` | JWT |
| `/crm` | `app/api/crm.py` | JWT |
| `/integracoes` | `app/api/integracoes.py` | JWT + público (callback) |

### Endpoints `/bot/*` (consumidos pelo n8n — `X-Bot-Token`)
`POST /bot/debounce`, `POST /bot/debounce/flush`, `GET /bot/services`,
`GET /bot/barbers`, `POST /bot/clients`, `PATCH /bot/clients/photo`,
`GET /bot/clients/profile`, `GET /bot/availability`, `POST /bot/appointments`,
`GET /bot/appointments`, `PATCH /bot/appointments/{id}/cancel`,
`PATCH /bot/appointments/{id}/complete`.

---

## 7. Páginas do frontend (confirmadas no código)

| Rota | Arquivo |
|---|---|
| `/login` | `app/login/page.tsx` |
| `/admin/agenda` | `app/admin/agenda/page.tsx` |
| `/admin/clientes` | `app/admin/clientes/page.tsx` |
| `/admin/dashboard` | `app/admin/dashboard/page.tsx` |
| `/admin/equipe` | `app/admin/equipe/page.tsx` |
| `/admin/financeiro` | `app/admin/financeiro/page.tsx` |
| `/admin/servicos` | `app/admin/servicos/page.tsx` |
| `/admin/crm` | `app/admin/crm/page.tsx` |
| `/admin/configuracoes` | `app/admin/configuracoes/page.tsx` (Suspense + Google Calendar) |
| `/barbeiro/agenda` | `app/barbeiro/agenda/page.tsx` (mobile-first) |

---

## 8. Migrations Alembic

Head atual (verificado na VM): **`0007_crm_leads`**.

```
0001_initial → 0002_loyalty → 0002_client_last_photo → 0003_client_photo_description
→ 0005_barber_services → 0006_client_blocked → 0007_crm_leads  ← HEAD
```

`integration_accounts`, `calendar_sync` e `message_log` existem desde `0001_initial`.
A Fase 2 (Calendar) **não criou migration nova**.

---

## 9. Dados e usuários em PRODUÇÃO (VM, org_id = 1)

**Única organização:** `id=1` — "Barbearia Taylor e Thedy".

**Barbeiros (`barbers`):** Taylor `id=1`, Thedy `id=2`, Marciana `id=3`,
Sandra `id=4`, Pablo `id=5`.

**Usuários de login (admin panel), todos org 1:**
`taylor@`, `thedy@`, `marciana@`, `sandra@`, `pablo@` `barbeariapro.com`.
Senha de seed: `senha123`.

**Roles do Postgres:** apenas `barber_app` (RLS, NOBYPASSRLS, senha `senha123`).
Admin via superuser `postgres`. Seed faz GRANT, não CREATE ROLE — o role
`barber_app` foi criado manualmente ao remontar a VM.

> ⚠️ Dois testes hardcoded em `organization_id == 3` falham contra qualquer banco
> org 1 (staging E a produção restaurada). São fails ambientais, não bugs.

---

## 10. Variáveis de ambiente

### Produção VM — `/opt/barbeariapro/.env` (valores reais ficam só na VM)
```
BOT_ORGANIZATION_ID=1
BOT_UNIT_ID=1
NEXT_PUBLIC_ORG_ID=1
EVOLUTION_INSTANCE_NAME=Barbearia      # B MAIÚSCULO, case-sensitive
EVOLUTION_SERVER_URL=http://34.95.199.134:8080
CORS_ORIGINS=http://34.95.199.134:3000
NEXT_PUBLIC_API_URL=http://34.95.199.134:8000
TZ=America/Sao_Paulo
# + BOT_API_KEY, EVOLUTION_API_KEY, OPENAI_API_KEY, POSTGRES_PASSWORD, SECRET_KEY
```

### Produção VM — `/opt/barbeariapro/.env.docker`
```
DATABASE_URL=postgresql+psycopg://barber_app:senha123@host.docker.internal:5432/barbeariapro
EVOLUTION_API_URL=http://host.docker.internal:8080
API_URL_INTERNAL=http://host.docker.internal:8000
AUTH_SECRET=<segredo>   AUTH_TRUST_HOST=true
```

### Staging local — `.env.staging` (gitignored)
```
DATABASE_URL=postgresql+psycopg://barber_app:senha123@localhost:5433/barbeariapro
EVOLUTION_API_URL=          # VAZIO — trava dry-run
EVOLUTION_INSTANCE_NAME=    # VAZIO — trava dry-run
BOT_API_KEY=staging-bot-key-isolada-fase2
GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI / TOKEN_ENCRYPTION_KEY
```

---

## 11. Trava de disparo WhatsApp (crítica)

`app/services/whatsapp.py:15-21` — `send_text()` retorna `False` sem enviar nada
se `EVOLUTION_API_URL` **ou** `EVOLUTION_INSTANCE_NAME` estiverem vazios.
É a principal barreira entre testes e disparo real. **Produção tem ambos preenchidos.**

---

## 12. Bot WhatsApp / n8n (produção)

- **Evolution:** v2.3.7, instância **`Barbearia`** (B maiúsculo — usada em
  `workflows.json` como `/message/sendText/Barbearia`). WhatsApp pareado ao
  número `5563920001734`.
- **Webhook:** Evolution → `http://host.docker.internal:5678/webhook/whatsapp`.
- **n8n v2.27.3** — 3 workflows ativos:
  - `BarbeariaPro Bot - WhatsApp Chatbot` (id `25QZQ664N6hrIg59`)
  - `BarbeariaPro Cron - Lembrete 24h` (id `CronReminder24h01`)
  - `BarbeariaPro Cron - Reativação Diária` (id `CronReactivation1`)
- **Persona:** "Raquel", recepcionista (system prompt no node `AI Agent`).
- **Modelo:** GPT-4o-mini (node `OpenAI GPT-4o-mini`, tipo `lmChatOpenAi`).
- **Credencial OpenAI:** ID `md1VzrcFUBhOFYfr` ("OpenAI account", tipo `openAiApi`).
- **Fluxo:** debounce (5s) → flush → AI Agent com tools `obter_perfil_cliente`,
  `listar_servicos`, `verificar_disponibilidade`, `criar_agendamento`, etc.,
  todas batendo em `http://host.docker.internal:8000/bot/*`.

> ⚠️ **n8n é frágil — leia D-14 antes de mexer.** NUNCA editar o SQLite direto nem
> apagar arquivos WAL. Sempre usar a API REST do n8n.

---

## 13. Suíte de testes

```bash
docker start barbeariapro-staging-postgres
set -a; . ./.env.staging; set +a
export SEED_ORG_ID=1
.venv/bin/python -m pytest tests/ -q
```

**Baseline:** ~206 pass / 2 fail ambientais / 4 skip.
Fails conhecidos (NÃO são bugs): testes hardcoded em `organization_id == 3`.
