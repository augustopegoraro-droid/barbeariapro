# PROJECT_CONTEXT.md
> Fonte de verdade para novas sessões de desenvolvimento.
> Verificado contra o código E contra a VM de produção em **2026-06-24** (última atualização: sessão CRM Conversacional Fases 2-5).

---

## 0. LEIA PRIMEIRO — o que mudou em 2026-06-24

1. **CRM Conversacional (Fases 2–5) implementado e deployado.**
   Tabelas `conversations`/`messages`/`attachments` no ar (migration `0010_conversations`).
   Bot grava toda mensagem em `messages`. Inbox com SSE em tempo real no frontend.
   Ver detalhes em §6, §8, §12 e §13.
2. **VM e repositório estão em sincronização total** — ambos em `f72cd59`.
   `git pull` na VM funciona normalmente desde a sessão parte 5.
3. **A Fase 2 (Google Calendar) já foi mergeada em `main`** (commit `1773b30`).
4. **Produção roda no próprio VM via docker-compose, NÃO no Cloud Run** (ver D-13).
5. **A produção usa `organization_id = 1`** — banco re-semeado do zero em 2026-06-23.
6. **D-20 superado:** a primeira mensagem de um novo número AGORA É gravada —
   `record_message` cria a conversa sem `client_id`; backfill ocorre na chegada do cliente.

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
> Commits de backend e frontend são feitos separadamente.
> O repo externo agora registra `barbearia-frontend` como gitlink (modo 160000) —
> isso é inofensivo para o deploy (feito via SCP + docker rebuild), mas commits do
> frontend devem continuar sendo feitos dentro do sub-repo (`git -C barbearia-frontend/ ...`).
> Ver D-08.

**Estado git (2026-06-24):**
- Branch `main`, commit `f72cd59` — **local E VM estão em sync**.
- Commits desta sessão: `f87f579` (Fase 2) → `70fd7e0` (fix dockerignore) →
  `7ee6cbf` (Fase 3) → `effdd77` (Fase 4 + SSE endpoint) → `f72cd59` (sse_broker + _publish).
- `workflows.json` local **diverge da VM** (tem conexões paralelas originais; VM tem série).
  Não usar como referência. Exportar da VM antes de editar. Ver D-18.

**Procedimento de deploy backend:**
```bash
gcloud compute ssh ubuntu@barbeariapro --project=barberiapro-app --zone=southamerica-east1-a \
  --command="sudo git -C /opt/barbeariapro pull origin main && \
  cd /opt/barbeariapro && sudo docker compose -f docker-compose.app.yml up -d --build backend"
```

**Procedimento de deploy frontend (scp, não git):**
```bash
gcloud compute scp --zone=southamerica-east1-a --project=barberiapro-app \
  barbearia-frontend/app/admin/crm/page.tsx ubuntu@barbeariapro:/tmp/crm_page.tsx
gcloud compute ssh ubuntu@barbeariapro --zone=southamerica-east1-a --project=barberiapro-app \
  --command="sudo cp /tmp/crm_page.tsx /opt/barbeariapro/barbearia-frontend/app/admin/crm/page.tsx && \
  cd /opt/barbeariapro && sudo docker compose -f docker-compose.app.yml up -d --build frontend"
```

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

### Containers em produção (verificado 2026-06-24)

```
barbeariapro-app-backend    :8000   (healthy)   FastAPI   — git f72cd59
barbeariapro-app-frontend   :3000   (healthy)   Next.js
barbeariapro-postgres       :5432   (healthy)   Postgres do app — migration HEAD: 0010_conversations
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
| `/crm` (conversas) | `app/api/conversations.py` | JWT / token param (SSE) |
| `/integracoes` | `app/api/integracoes.py` | JWT + público (callback) |

### Endpoints `/bot/*` (consumidos pelo n8n — `X-Bot-Token`)
`POST /bot/debounce`, `POST /bot/debounce/flush`, `GET /bot/services`,
`GET /bot/barbers`, `POST /bot/clients`, `PATCH /bot/clients/photo`,
`GET /bot/clients/profile`, `GET /bot/clients/paused-status`,
`GET /bot/availability`, `POST /bot/appointments`,
`GET /bot/appointments`, `PATCH /bot/appointments/{id}/cancel`,
`PATCH /bot/appointments/{id}/complete`,
`POST /bot/messages` — grava mensagem inbound/outbound via `conversation_service`;
  idempotente por `(conversation_id, wa_message_id, sender_type)`; grava mesmo sem
  cliente cadastrado (1º contato); avança lead `novo_contato→conversando` no inbound.

### Endpoints `/crm/*` (JWT, `app/api/crm.py`)
`GET /crm/board`, `POST /crm/leads`, `GET /crm/leads/{id}`,
`PATCH /crm/leads/{id}`, `POST /crm/leads/{id}/move`, `DELETE /crm/leads/{id}`,
`GET /crm/leads/{id}/messages` — histórico de conversa via `Conversation.client_id`
  (agora lê de `messages`, não de `message_log`).

### Endpoints `/crm/*` (JWT, `app/api/conversations.py`) — Fase 3/4/5
`GET /crm/conversations` — lista paginada por cursor (base64 JSON), JOIN com clients/leads,
  total_open count; `?status=open|snoozed|closed`, `?assigned_user_id=N`.
`GET /crm/conversations/search?q=` — ILIKE em `messages.body_text` via índice GIN pg_trgm.
`GET /crm/conversations/{id}` — detalhe com client e lead.
`GET /crm/conversations/{id}/messages` — scroll infinito por cursor `?before=<id>`, `?limit=N`;
  inclui `attachments` via `selectinload`.
`PATCH /crm/conversations/{id}/read` — zera `unread_count`.
`GET /crm/stream?token=<jwt>` — **SSE em tempo real**; token como query param porque
  browser `EventSource` não suporta headers customizados; keepalive a cada 25 s;
  publica evento `new_message` com payload completo (ver D-21, D-23).

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
| `/admin/crm` | `app/admin/crm/page.tsx` — toggle Kanban ⇄ Inbox |
| `/admin/configuracoes` | `app/admin/configuracoes/page.tsx` (Suspense + Google Calendar) |
| `/barbeiro/agenda` | `app/barbeiro/agenda/page.tsx` (mobile-first) |

---

## 8. Migrations Alembic

Head atual (verificado na VM em 2026-06-24): **`0010_conversations`**.

```
0001_initial → 0002_loyalty → 0002_client_last_photo → 0003_client_photo_description
→ 0005_barber_services → 0006_client_blocked → 0007_crm_leads
→ 0008_client_bot_paused → 0009_conversation_log → 0010_conversations  ← HEAD
```

- `0009_conversation_log` — coluna `body_text TEXT` em `message_log`
- `0010_conversations` — tabelas `conversations`, `messages`, `attachments` com RLS,
  ENUMs `conversation_status`/`message_sender_type`/`message_type`/`attachment_media_type`,
  índice GIN pg_trgm em `messages.body_text`, índice parcial de idempotência
  `(conversation_id, wa_message_id, sender_type) WHERE wa_message_id IS NOT NULL`,
  backfill do `message_log` para `messages` (idempotente, ON CONFLICT DO NOTHING).

> ⚠️ **Migrations precisam de superuser postgres para DDL** — `barber_app` não tem
> privilégio CREATE TYPE/TABLE. Para rodar na VM:
> ```bash
> sudo docker exec -e DATABASE_URL="postgresql+psycopg://postgres:<SENHA>@host.docker.internal:5432/barbeariapro" \
>   barbeariapro-app-backend python -m alembic upgrade head
> ```
> A senha do postgres está no `.env` da VM como `POSTGRES_PASSWORD`.
> Ver também `Dockerfile.migrate.dockerignore` (D-25).

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

**Clientes reais cadastrados (verificado 2026-06-23):**
- `id=1` Augusto Pegoraro — `+556399368196` (dono da conta)
- `id=5` Reinaldo Viterbo — `+5563999789977`

**Leads no Kanban (verificado 2026-06-23):**
- `id=1` "Cliente Teste Funil" — estágio `agendado`, sem `client_id`
- `id=4` "Augusto Pegoraro" — estágio `novo_contato`, `client_id=1`

> ⚠️ **Número do WhatsApp de Augusto:** Evolution API envia `+556399368196`
> (8 dígitos após DDD). O usuário pode informar como `+5563999368196` (9 dígitos).
> São o mesmo número normalizado pela Evolution. O DB usa o formato da Evolution.

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
  - `BarbeariaPro Bot - WhatsApp Chatbot` (id `25QZQ664N6hrIg59`, **43 nós**)
  - `BarbeariaPro Cron - Lembrete 24h` (id `CronReminder24h01`)
  - `BarbeariaPro Cron - Reativação Diária` (id `CronReactivation1`)
- **Persona:** "Raquel", recepcionista (system prompt no node `AI Agent`).
- **Modelo:** GPT-4o-mini (node `OpenAI GPT-4o-mini`, tipo `lmChatOpenAi`).
- **Credencial OpenAI:** ID `md1VzrcFUBhOFYfr` ("OpenAI account", tipo `openAiApi`).

### Fluxo principal do bot (VERIFICADO NA VM)

```
Webhook → Block List → Set Phone → IF Is Audio / IF Individual / IF Has Image
→ HTTP Debounce → IF Controller → Wait 5s → HTTP Flush Buffer
→ Log Inbound Message          (POST /bot/messages, direction=inbound)
→ Code Horário Comercial       usa $('HTTP Flush Buffer').first().json.* (refs explícitas)
→ IF Horário Aberto
→ Send Composing → Wait Typing Init → Send Composing Active
→ HTTP Check Bot Pause → IF Bot Paused
→ Memory → AI Agent (com tools abaixo)
→ Send Response
→ Log Outbound Message         (POST /bot/messages, direction=outbound)
```

### Tools do AI Agent
`obter_perfil_cliente` (`GET /bot/clients/profile`),
`cadastrar_cliente` (`POST /bot/clients`),
`listar_servicos` (`GET /bot/services`),
`listar_barbeiros` (`GET /bot/barbers`),
`verificar_disponibilidade` (`GET /bot/availability`),
`criar_agendamento` (`POST /bot/appointments`),
`consultar_agendamentos` (`GET /bot/appointments`),
`cancelar_agendamento` (`PATCH /bot/appointments/{id}/cancel`),
`faq` (Code node local).

### Nós de Log — detalhes críticos
- **Tipo:** `n8n-nodes-base.httpRequest` v4.4, `onError: continueRegularOutput`
- **URL:** `http://host.docker.internal:8000/bot/messages`
- **Auth:** header `X-Bot-Token: ={{ $env.BOT_API_KEY }}`
- **Body format:** `specifyBody: "json"`, `jsonBody: "={{ {phone: ..., direction: ..., body: ...} }}"`
- **Posição:** EM SÉRIE, não paralelo (ver D-18)
- **Log Inbound:** referencia `$('HTTP Flush Buffer').item.json.message`
- **Log Outbound:** referencia `$('AI Agent').item.json.output`

> ⚠️ **n8n é frágil — leia D-14 e D-18 antes de mexer.** NUNCA editar o SQLite direto.
> O `workflows.json` local diverge da VM; a fonte de verdade é a VM via API REST.

### Autenticação n8n (API REST)
Cookie de sessão expira. Para renovar:
```bash
python3 -c "
import json, urllib.request
body = json.dumps({'emailOrLdapLoginId': 'admin@barbeariapro.com', 'password': 'Barbearia2026'}).encode()
r = urllib.request.urlopen(urllib.request.Request('http://localhost:5678/rest/login', body, {'Content-Type': 'application/json'}))
print([h for h in r.headers.items() if 'set-cookie' in h[0].lower()])
"
```

---

## 13. CRM Conversacional — arquitetura (Fases 2–5)

### Modelo de dados
- `conversations` — uma por `(org, phone, channel)`; `UNIQUE(organization_id, phone_e164, channel)`;
  FK nullable para `clients` e `leads` (SET NULL se deletados); `unread_count`, `last_message_at`,
  `last_message_preview`, `bot_active`, `status`.
- `messages` — cada mensagem; `sender_type`: `client|bot|human|system`; `message_type`: `text|audio|image|document|event`;
  FK para `conversation_id` (NOT NULL), `sender_user_id` (nullable), `message_log_id` (nullable FK para `message_log`).
- `attachments` — mídia; FK `message_id` CASCADE; `media_type`: `audio|image|document|video`.

### Porta única de escrita: `app/services/conversation.py`
- `get_or_create_conversation(db, org_id, phone, *, client_id, channel)` — upsert atômico,
  backfill de `client_id` e `lead_id` se NULL.
- `record_message(db, *, org_id, phone, sender_type, body, ...)` — idempotente por
  `(conversation_id, wa_message_id, sender_type)` onde `wa_message_id IS NOT NULL`;
  atualiza `last_message_at`/`preview`/`unread_count`; chama `_publish` após `flush()`.
- `_publish` — publica evento no `sse_broker` com payload completo (não requer GET adicional).
- **Quem chama:** `bot.py:log_message`, `reminders.py`, `reactivation.py`.
- **Invariante:** `message_log` é intocado por este serviço — continua sendo usado para
  reminders/reativação com template/retry. `messages` é o store canônico de conversa (ver D-26).

### SSE broker: `app/services/sse_broker.py`
- `_subs: dict[int, set[asyncio.Queue]]` — `org_id → set de filas` (uma por conexão SSE aberta).
- Single-process (asyncio); safe para deploy sem `--workers`. Para múltiplos workers, migrar
  para PostgreSQL LISTEN/NOTIFY (ver D-21).
- `subscribe(org_id)` → Queue; `unsubscribe(org_id, q)`; `publish(org_id, event)` — drop silencioso
  se `QueueFull` (consumer lento).

### Frontend (page.tsx `/admin/crm`)
- Toggle **Kanban ⇄ Inbox** no cabeçalho da página CRM.
- **InboxView:** lista de conversas com cursor pagination; abre `EventSource` no mount
  (`GET /crm/stream?token=`); eventos `new_message` atualizam preview/unread na lista
  e propagam `sseMsg` para o painel ativo.
- **ConvMessagePanel:** scroll infinito com `before=<id>`; recebe `sseMsg` via prop e
  appenda com deduplicação por `id`; polling 10 s como fallback; `PATCH /read` ao abrir.
- Polling (10 s / 15 s) permanece como fallback caso SSE caia.

---

## 14. Suíte de testes

```bash
docker start barbeariapro-staging-postgres
set -a; . ./.env.staging; set +a
export SEED_ORG_ID=1
.venv/bin/python -m pytest tests/ -q
```

**Baseline:** ~206 pass / 2 fail ambientais / 4 skip.
Fails conhecidos (NÃO são bugs): testes hardcoded em `organization_id == 3`.
