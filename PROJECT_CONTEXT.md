# PROJECT_CONTEXT.md
> Fonte de verdade para novas sessões de desenvolvimento.
> Verificado contra o código E contra a VM de produção em **2026-06-24** (última atualização: sessão webhook direto Evolution→FastAPI + correções CRM).

---

## 0. LEIA PRIMEIRO — o que mudou em 2026-06-24 (2ª sessão)

1. **Webhook direto Evolution→FastAPI implementado** (`app/api/wa_webhook.py`).
   Evolution agora aponta para `http://host.docker.internal:8000/bot/wa-webhook`.
   Mensagens de cliente chegam **sem o delay de 5 s do n8n** e disparam SSE imediatamente.
2. **Migration `0011_grant_crm_tables` aplicada** — `barber_app` agora tem CRUD em
   `conversations`, `messages`, `attachments`. Sem ela, `record_message` falhava com
   `InsufficientPrivilege`.
3. **n8n workflow reconfigurado** — `Log Inbound Message` desabilitado (cliente já gravado
   pelo webhook direto); `HTTP Flush Buffer` conecta direto em `Code Horário Comercial`;
   `Log Outbound Message` usa `$json["key"]["remoteJid"]` (resposta da Evolution, mais robusto).
4. **Evento `SEND_MESSAGE` adicionado ao webhook da Evolution** — para capturar mensagens
   enviadas pelo bot. Código implementado em `wa_webhook.py` mas **AINDA NÃO CONFIRMADO**
   funcionando (bot responses não aparecem no CRM — investigação em andamento).
5. **Credenciais n8n alteradas** (acidente `user-management:reset`) — ver §12 e D-28.
6. **`N8N_WEBHOOK_URL` adicionado ao `.env.docker`** para o forward background.

---

## 1. O que é o projeto

**BarbeariaPro** — plataforma SaaS de gestão para barbearias e salões.
Cliente âncora em produção: **Barbearia Taylor & Thedy** (Palmas/TO), clientes reais.
Objetivo comercial: vender para mais barbearias; concorre com Trinks.

---

## 2. Repositórios e estrutura de arquivos

| Repo / Diretório | Branch | Conteúdo |
|---|---|---|
| `/Users/apleandro/dev/barbeariapro` | `main` | Backend FastAPI + infra Docker + workflows n8n |
| `/Users/apleandro/dev/barbeariapro/barbearia-frontend` | `main` | Frontend Next.js (repo git **separado** dentro do diretório) |

> **Atenção:** `barbearia-frontend/` é um sub-repositório git independente.
> Commits de backend e frontend são feitos separadamente. Ver D-08.

**Estado git (2026-06-24, fim da 2ª sessão):**
- Branch `main`, commit `dfdf7b9` — **local E VM estão em sync**.
- Commits desta sessão (sobre `f72cd59`):
  - `3fe1085` — `app/api/wa_webhook.py` (webhook direto Evolution)
  - `2c0cc2a` — migration `0011_grant_crm_tables`
  - `94aa8fc` — `fromMe=true` handling no webhook
  - `3f7e2f8` — tratamento de evento `send.message`
  - `b8a793c`, `dfdf7b9` — debug logging (TEMPORÁRIO — remover após confirmar send.message)
- `workflows.json` local: **NÃO usar como referência**. Fonte de verdade = VM via API REST.

**Procedimento de deploy backend:**
```bash
gcloud compute ssh apleandro@barbeariapro --zone=southamerica-east1-a \
  --command="cd /opt/barbeariapro && sudo git pull origin main && \
  sudo docker compose -f docker-compose.app.yml restart backend"
```
> Nota: usa `restart` (não `up --build`) para deploys sem mudança de dependências.
> `up --build` é necessário apenas quando `requirements.txt` ou `Dockerfile` muda.

**Procedimento de deploy frontend (scp, não git):**
```bash
gcloud compute scp --zone=southamerica-east1-a \
  barbearia-frontend/app/admin/crm/page.tsx apleandro@barbeariapro:/tmp/crm_page.tsx
gcloud compute ssh apleandro@barbeariapro --zone=southamerica-east1-a \
  --command="sudo cp /tmp/crm_page.tsx /opt/barbeariapro/barbearia-frontend/app/admin/crm/page.tsx && \
  cd /opt/barbeariapro && sudo docker compose -f docker-compose.app.yml up -d --build frontend"
```

---

## 3. Stack tecnológica

### Backend
- **Python 3.9**, FastAPI, SQLAlchemy async (psycopg3), Alembic
- **PostgreSQL 16** com Row Level Security (multi-tenant por `organization_id`)
- Auth: JWT Bearer (`app/core/security.py`) + header **`X-Bot-Token`** para o bot
  (`app/api/bot.py:109`, validado contra `settings.bot_api_key`)
- Criptografia de tokens OAuth: Fernet (`app/core/crypto.py`)

### Frontend
- **Next.js** App Router — leia `barbearia-frontend/AGENTS.md` antes de mexer
- next-auth (sessão JWT), Tailwind CSS, Axios (`barbearia-frontend/lib/api.ts`)
- `useSearchParams()` exige `<Suspense>` boundary

### Infraestrutura
- **Docker Compose** — dois arquivos:
  - `docker-compose.yml`: infra (Postgres prod `:5432`, n8n `:5678`, Evolution `:8080`,
    evolution-postgres, evolution-redis)
  - `docker-compose.app.yml`: app (backend `:8000`, frontend `:3000`)
- O `docker-compose.app.yml` usa `.env.docker` para sobrescrever variáveis para containers.

---

## 4. PRODUÇÃO REAL — VM GCP (origem da verdade operacional)

| Item | Valor |
|---|---|
| Projeto GCP | `barberiapro-app` |
| VM | `barbeariapro` |
| Zona | `southamerica-east1-a` |
| IP externo | `34.95.199.134` |
| Acesso SSH | `gcloud compute ssh apleandro@barbeariapro --zone=southamerica-east1-a` |
| App na VM | `/opt/barbeariapro` |

### Containers em produção (verificado 2026-06-24, ~17:30)

```
barbeariapro-app-backend    :8000   Up ~1h (healthy)   FastAPI   — git dfdf7b9
barbeariapro-app-frontend   :3000   Up ~5h (healthy)   Next.js
barbeariapro-postgres       :5432   Up ~26h (healthy)  Postgres  — migration HEAD: 0011_grant_crm_tables
evolution_api               :8080   Up ~26h            Evolution API v2.3.7
evolution_postgres          (interno)
evolution_redis             (interno)
n8n                         :5678   Up ~23h            n8n v2.27.3
```

### Acessos administrativos
- **n8n editor:** `http://34.95.199.134:5678`
  - Login: `admin@barbearia.com` / `Barbearia@2026!` ← **ATUALIZADO** (ver D-28)
  - Cookie de sessão salvo em `/tmp/n8n_cookies` na VM (expira; renovar com POST /rest/login)
- **Evolution manager:** `http://34.95.199.134:8080/manager` — login com `EVOLUTION_API_KEY`
- **App frontend:** `http://34.95.199.134:3000`
- **App backend:** `http://34.95.199.134:8000`
- **Postgres (admin):** `docker exec barbeariapro-postgres psql -U postgres -d barbeariapro`

### Firewall (target-tag `http-server`)
`allow-evolution` (8080), `allow-n8n` (5678), `allow-backend` (8000), `allow-frontend` (3000).
> ⚠️ Todas as portas estão abertas ao mundo. HTTPS/domínio ainda NÃO configurado.

---

## 5. Ambientes

| Ambiente | Onde | Banco | Evolution/Bot |
|---|---|---|---|
| **Produção** | VM GCP `34.95.199.134` | `barbeariapro-postgres:5432` (org 1) | **ATIVO** — dispara WhatsApp real |
| **Staging** | local (Mac) | `barbeariapro-staging-postgres:5433` | **VAZIO** (dry-run) |

> D-01: `EVOLUTION_API_URL` e `EVOLUTION_INSTANCE_NAME` **VAZIOS** em staging.

---

## 6. Rotas da API (confirmadas no código)

| Prefixo | Arquivo | Auth |
|---|---|---|
| `/health` | `app/api/health.py` | público |
| `/auth` | `app/api/auth.py` | público (login) |
| `/bot` | `app/api/bot.py` | **`X-Bot-Token`** |
| `/bot/wa-webhook` | `app/api/wa_webhook.py` | `X-Webhook-Secret` (opcional) |
| `/crm` | `app/api/crm.py` | JWT |
| `/crm` (conversas) | `app/api/conversations.py` | JWT / token param (SSE) |
| `/integracoes` | `app/api/integracoes.py` | JWT + público (callback) |
| ... demais | ver rotas padrão | JWT |

### Endpoint `/bot/wa-webhook` — webhook proxy Evolution→FastAPI
`POST /bot/wa-webhook` — recebe eventos Evolution API:
- **`messages.upsert`** (fromMe=false): grava mensagem do cliente (`sender_type=client`) → SSE imediato
- **`messages.upsert`** (fromMe=true): grava como bot — mas Evolution v2.3.7 **NÃO dispara** este evento para msgs enviadas via API
- **`send.message`**: evento para msgs enviadas pelo bot; grava como `sender_type=bot`; **NÃO encaminha ao n8n** (evita loop)
- Outros eventos: encaminhados ao n8n em background (retry 3× com backoff)
- Autenticação: `X-Webhook-Secret` header (se `WA_WEBHOOK_SECRET` configurado no env)
- Debug temporário: `print(f"[WA_WEBHOOK] event=...")` nos logs — **REMOVER** após confirmar `send.message`

### Endpoints `/bot/*` (consumidos pelo n8n — `X-Bot-Token`)
`POST /bot/debounce`, `POST /bot/debounce/flush`, `GET /bot/services`,
`GET /bot/barbers`, `POST /bot/clients`, `GET /bot/clients/profile`,
`GET /bot/clients/paused-status`, `GET /bot/availability`,
`POST /bot/appointments`, `GET /bot/appointments`,
`PATCH /bot/appointments/{id}/cancel`, `PATCH /bot/appointments/{id}/complete`,
`POST /bot/messages` — grava mensagem via `conversation_service`; idempotente por
`(conversation_id, wa_message_id, sender_type)`; grava sem cliente (1º contato).

### Endpoints `/crm/*` (JWT, conversations.py) — Inbox em tempo real
`GET /crm/conversations`, `GET /crm/conversations/search?q=`,
`GET /crm/conversations/{id}`, `GET /crm/conversations/{id}/messages`,
`PATCH /crm/conversations/{id}/read`,
`POST /crm/conversations/{id}/send` — envia mensagem pelo Inbox (via Evolution),
`GET /crm/stream?token=<jwt>` — **SSE em tempo real**.

---

## 7. Páginas do frontend (confirmadas no código)

| Rota | Arquivo |
|---|---|
| `/login` | `app/login/page.tsx` |
| `/admin/agenda` | `app/admin/agenda/page.tsx` |
| `/admin/clientes` | `app/admin/clientes/page.tsx` |
| `/admin/dashboard` | `app/admin/dashboard/page.tsx` |
| `/admin/crm` | `app/admin/crm/page.tsx` — toggle Kanban ⇄ Inbox |
| ... demais | padrão |

---

## 8. Migrations Alembic

Head atual (verificado na VM em 2026-06-24): **`0011_grant_crm_tables`**.

```
0001_initial → 0002_loyalty → 0002_client_last_photo → 0003_client_photo_description
→ 0005_barber_services → 0006_client_blocked → 0007_crm_leads
→ 0008_client_bot_paused → 0009_conversation_log → 0010_conversations
→ 0011_grant_crm_tables  ← HEAD
```

- `0010_conversations` — tabelas `conversations`/`messages`/`attachments` com RLS e índices
- `0011_grant_crm_tables` — `GRANT SELECT,INSERT,UPDATE,DELETE ON conversations,messages,attachments TO barber_app` + `GRANT USAGE,SELECT ON ALL SEQUENCES`

> ⚠️ **Migrations precisam de superuser postgres** — `barber_app` não tem privilégio CREATE TYPE/TABLE.
> A `0011` foi pré-aplicada manualmente e depois commitada; alembic_version já estava em `0011` antes do `upgrade head`.

---

## 9. Dados e usuários em PRODUÇÃO (VM, org_id = 1)

**Única organização:** `id=1` — "Barbearia Taylor e Thedy".

**Clientes reais:**
- `id=1` Augusto Pegoraro — `+556399368196` (dono da conta, número em formato 8 dígitos)
- `id=5` Reinaldo Viterbo — `+5563999789977`

**Conversas no DB (verificado 2026-06-24):**
- `conv_id=1`: phone `+556399368196` — conversa real do Augusto (maioria das msgs)
- `conv_id=2`: phone `+5511999990000` — teste mock
- `conv_id=10`: phone `+5563999368196` — criado por teste manual com 9 dígitos

> ⚠️ **Formato de telefone:** Evolution envia `556399368196@s.whatsapp.net` (8 dígitos).
> O mesmo número pode ser `+5563999368196` (9 dígitos) em outras fontes.
> **NÃO APLICAR** a conversão 8→9 no `normalize_phone` sem antes migrar o DB — conv_id=1
> tem o número em 8 dígitos e a conversão quebraria o lookup. Ver D-29.

**Roles do Postgres:** apenas `barber_app` (RLS, NOBYPASSRLS, senha `senha123`).
Admin via superuser `postgres`.

---

## 10. Variáveis de ambiente

### Produção VM — `/opt/barbeariapro/.env`
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
# WA_WEBHOOK_SECRET não configurado (webhook sem autenticação por agora)
```

### Produção VM — `/opt/barbeariapro/.env.docker`
```
DATABASE_URL=postgresql+psycopg://barber_app:senha123@host.docker.internal:5432/barbeariapro
EVOLUTION_API_URL=http://host.docker.internal:8080
N8N_WEBHOOK_URL=http://host.docker.internal:5678    ← NOVO (forward background)
API_URL_INTERNAL=http://host.docker.internal:8000
AUTH_SECRET=<segredo>   AUTH_TRUST_HOST=true
# WA_WEBHOOK_SECRET=    ← comentado (opcional, para autenticar webhook)
```

---

## 11. Trava de disparo WhatsApp (crítica)

`app/services/whatsapp.py:15-21` — `send_text()` retorna `False` sem enviar nada
se `EVOLUTION_API_URL` **ou** `EVOLUTION_INSTANCE_NAME` estiverem vazios.

---

## 12. Bot WhatsApp / n8n (produção)

- **Evolution:** v2.3.7, instância **`Barbearia`** (B maiúsculo). WhatsApp pareado ao
  número `5563920001734`.
- **Webhook Evolution:** aponta para **`http://host.docker.internal:8000/bot/wa-webhook`**
  ← ALTERADO nesta sessão (antes apontava para n8n `:5678/webhook/whatsapp`)
- **Eventos webhook:** `MESSAGES_UPSERT`, `SEND_MESSAGE`, `CONNECTION_UPDATE`, `QRCODE_UPDATED`
  ← `SEND_MESSAGE` adicionado nesta sessão
- **n8n v2.27.3** — 3 workflows ativos:
  - `BarbeariaPro Bot - WhatsApp Chatbot` (id `25QZQ664N6hrIg59`, **43 nós**, versionId `3473de06`)
  - `BarbeariaPro Cron - Lembrete 24h` (id `CronReminder24h01`)
  - `BarbeariaPro Cron - Reativação Diária` (id `CronReactivation1`)
- **n8n login:** `admin@barbearia.com` / `Barbearia@2026!` ← **ATUALIZADO** (ver D-28)
- **Persona:** "Raquel", recepcionista (system prompt no node `AI Agent`).
- **Modelo:** GPT-4o-mini (node `OpenAI GPT-4o-mini`, tipo `lmChatOpenAi`).
- **Credencial OpenAI:** ID `md1VzrcFUBhOFYfr` ("OpenAI account").

### Fluxo do bot (VERIFICADO NA VM — workflow versionId `3473de06`)

```
Webhook → Block List → Set Phone → IF Is Audio / IF Individual / IF Has Image
→ HTTP Debounce → IF Controller → Wait 5s → HTTP Flush Buffer
→ Code Horário Comercial    ← direto (Log Inbound Message DESABILITADO — ver D-30)
→ IF Horário Aberto
→ Send Composing → Wait Typing Init → Send Composing Active
→ HTTP Check Bot Pause → IF Bot Paused
→ Memory → AI Agent (com tools abaixo)
→ Send Response
→ Log Outbound Message      (POST /bot/messages, direction=outbound)
```

> ⚠️ **Log Outbound Message** usa `$json["key"]["remoteJid"]` e `$json["message"]["conversation"]`
> (dados da resposta da Evolution API retornada pelo `Send Response`) — não usa mais `$('AI Agent')`.
> Isso evita quebra de expressão por expansão de `$` na shell durante configuração via API REST.

### Tools do AI Agent (inalteradas)
`obter_perfil_cliente`, `cadastrar_cliente`, `listar_servicos`, `listar_barbeiros`,
`verificar_disponibilidade`, `criar_agendamento`, `consultar_agendamentos`,
`cancelar_agendamento`, `faq`.

### Autenticação n8n (API REST)
```bash
# Na VM, renovar cookie:
curl -s -c /tmp/n8n_cookies -X POST 'http://localhost:5678/rest/login' \
  -H 'Content-Type: application/json' \
  -d '{"emailOrLdapLoginId":"admin@barbearia.com","password":"Barbearia@2026!"}'

# Atualizar workflow:
curl -sb /tmp/n8n_cookies -X PATCH \
  'http://localhost:5678/rest/workflows/25QZQ664N6hrIg59' \
  -H 'Content-Type: application/json' -d @/tmp/wf_payload.json
```

> ⚠️ **D-14**: NUNCA editar SQLite do n8n. SEMPRE via API REST.
> ⚠️ **D-18**: NUNCA conectar nós em paralelo. SEMPRE em série.
> ⚠️ **D-29**: Expressões `$('NomeNó')` em payloads passados via SSH double-quote têm `$`
> expandido pela shell. Escrever payload em arquivo Python antes de enviar via curl.

---

## 13. CRM Conversacional — arquitetura (Fases 2–5 + webhook direto)

### Fluxo completo de uma mensagem do cliente
```
WhatsApp → Evolution → POST /bot/wa-webhook → record_message(sender=client) → SSE → Inbox
                     ↓ (background, retry 3×)
                     n8n webhook → debounce → AI Agent → Send Response (Evolution)
                                                       → Log Outbound Message
                                                         → POST /bot/messages (direction=outbound)
                                                           → record_message(sender=bot) → SSE → Inbox
```

> ⚠️ **Bot responses ainda não confirmadas no Inbox** (2026-06-24):
> - `Log Outbound Message` conectado e `$json` expression correta, mas:
>   - O snapshot do workflow usado nas execuções 80/81 (14:09/14:22) NÃO tinha o nó
>     (foi adicionado depois — mesmo versionId por quirk do n8n)
>   - `SEND_MESSAGE` via Evolution webhook: código implementado mas comportamento
>     não confirmado (Evolution pode não disparar esse evento para msgs via API)
> - Debug logging ativo (`print [WA_WEBHOOK]` nos logs do backend)
> - **PRÓXIMO PASSO:** enviar msg WhatsApp, ler logs, confirmar evento e remover debug

### Modelo de dados
- `conversations` — `UNIQUE(organization_id, phone_e164, channel)`; FK nullable para `clients`/`leads`
- `messages` — `sender_type`: `client|bot|human|system`; idempotência por `(conv_id, wa_message_id, sender_type) WHERE wamid IS NOT NULL`
- `attachments` — mídia; FK `message_id` CASCADE

### Porta única de escrita: `app/services/conversation.py`
- `record_message` — idempotente; atualiza preview/unread; chama `_publish` após `flush()`
- `_publish` — publica no SSE broker com payload completo

### SSE broker: `app/services/sse_broker.py`
- Single-process (asyncio). Para múltiplos workers: migrar para PostgreSQL LISTEN/NOTIFY.

---

## 14. Suíte de testes

```bash
docker start barbeariapro-staging-postgres
set -a; . ./.env.staging; set +a
export SEED_ORG_ID=1
.venv/bin/python -m pytest tests/ -q
```

**Baseline:** ~206 pass / 2 fail ambientais / 4 skip.
Fails conhecidos (NÃO são bugs): testes hardcoded em `organization_id == 3` (ver D-17).
