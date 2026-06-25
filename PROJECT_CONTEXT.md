# PROJECT_CONTEXT.md
> Fonte de verdade para novas sessões de desenvolvimento.
> Verificado contra o código E contra a VM de produção em **2026-06-25** (2ª sessão: auditoria bot + integracoes WhatsApp).

---

## 0. LEIA PRIMEIRO — o que mudou em 2026-06-25 (2ª sessão)

1. **Bot corrigido** — system prompt do AI Agent atualizado: Marciana (id=3), Sandra (id=4) e Pablo (id=5)
   adicionados à seção `OS BARBEIROS`. O prompt anterior listava apenas Taylor e Thedy, causando o bot
   a negar que outros funcionários trabalhavam na barbearia. versionId n8n: `8ae50a30-49ac-4cd1-b290-e7e68bd89c25`.
2. **WhatsApp reconectado** — VM estava TERMINATED desde ~24/06. Religada. Instância Evolution deletada
   e recriada (nova sessão WA). QR escaneado. Estado: `open`.
3. **Webhook Evolution corrigido** — ao recriar instância, o webhook foi erroneamente apontado para o n8n.
   Corrigido de volta para `http://host.docker.internal:8000/bot/wa-webhook` (FastAPI). CRM inbox funcional.
4. **Página `/admin/integracoes` implementada** — substituiu placeholder "em desenvolvimento" por:
   - Card WhatsApp com status (verde/vermelho) + número conectado.
   - Botão "Conectar/Reconectar" que abre modal com QR code gerado pela Evolution API.
   - QR auto-atualiza a cada 30s; detecta conexão automaticamente e fecha o modal.
   - Backend: `GET /integracoes/whatsapp/status` + `GET /integracoes/whatsapp/qr`.
5. **Senha n8n resetada** — login estava falhando; senha redefinida para `Barbearia2026` (ver D-28 atualizado).
6. **Lembrete 24h** — confirmado saudável: 5 execuções bem-sucedidas em 2026-06-24. Parou porque VM
   estava desligada. Voltou a rodar automaticamente ao ligar a VM.

### O que mudou em 2026-06-25 (1ª sessão — frontend shell + nginx)

1. **Admin shell** — `AdminSidebar`, `AdminHeader`, `AdminShell` em `components/layout/`. Layout em `app/admin/layout.tsx`.
2. **shadcn/ui v4** com Tailwind v4.
3. **6 rotas admin novas**: `/admin/conversas` (redirect → `/admin/crm?view=inbox`), mais 5 placeholders.
4. **nginx** — proxy reverso porta 80 → `localhost:3000`. Config: `/etc/nginx/sites-available/barbeariapro`.

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

> **Atenção:** `barbearia-frontend/` tem seu próprio `.git` com remote apontando para
> `https://github.com/DoctorDCombo/barbearia-frontend.git` — **este repo NÃO EXISTE mais**.
> Commits locais existem mas não têm push remoto funcional. Deploy é feito via scp+SSH+docker build na VM.

**Estado git (2026-06-25, 2ª sessão):**
- Backend (`main`): commit `3e138b5` — local e VM em sync.
- Frontend (`main`): commit `f5397a8` — apenas local (push remoto falha; deploy via scp+build na VM).

**Procedimento de deploy backend (sem mudança de dependências):**
```bash
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command=\
  "sudo git -C /opt/barbeariapro pull && \
   cd /opt/barbeariapro && sudo docker compose -f docker-compose.app.yml up -d --build backend"
```

**Procedimento de deploy frontend (scp + build):**
```bash
# 1. Copiar arquivo(s) modificado(s) para a VM:
gcloud compute scp /Users/apleandro/dev/barbeariapro/barbearia-frontend/app/admin/integracoes/page.tsx \
  barbeariapro:/tmp/page.tsx --project=barberiapro-app --zone=southamerica-east1-a
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command=\
  "sudo cp /tmp/page.tsx /opt/barbeariapro/barbearia-frontend/app/admin/integracoes/page.tsx"

# 2. Reconstruir e reiniciar container:
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command=\
  "cd /opt/barbeariapro && sudo docker compose -f docker-compose.app.yml up -d --build frontend"
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
- **Next.js 16** App Router — leia `barbearia-frontend/AGENTS.md` antes de mexer
- **TypeScript** strict mode
- **Tailwind CSS v4** (`@import "tailwindcss"` — sem `tailwind.config.ts`)
- **shadcn/ui v4.11.0** com Tailwind v4 — usa `@base-ui/react` (não Radix UI)
- **next-auth v5** (beta) com `proxy.ts` (middleware de auth)
- **Inter font** via `next/font/google` (não Geist)
- `useSearchParams()` exige `<Suspense>` boundary — preferir `window.location.search` em client components
- Admin shell: `AdminSidebar` + `AdminHeader` em `components/layout/`; compostos por `AdminShell`
- **Padrão de chamada API:** `authedApi(token).get/post(...)` de `@/lib/api`

### Infraestrutura
- **Docker Compose** — dois arquivos:
  - `docker-compose.yml`: infra (Postgres prod `:5432`, n8n `:5678`, Evolution `:8080`,
    evolution-postgres, evolution-redis)
  - `docker-compose.app.yml`: app (backend `:8000`, frontend `:3000`)
- **nginx v1.22.1** instalado no host da VM — proxy reverso na porta 80 (ver §4)

---

## 4. PRODUÇÃO REAL — VM GCP (origem da verdade operacional)

| Item | Valor |
|---|---|
| Projeto GCP | `barberiapro-app` |
| VM | `barbeariapro` |
| Zona | `southamerica-east1-a` |
| IP externo | `34.95.199.134` |
| Acesso SSH | `gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a` |
| App na VM | `/opt/barbeariapro` |

> **Atenção:** A VM já foi desligada involuntariamente em 2026-06-25 (ficou TERMINATED).
> Verificar status antes de qualquer sessão: `gcloud compute instances describe barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --format="value(status)"`
> Para ligar: `gcloud compute instances start barbeariapro --project=barberiapro-app --zone=southamerica-east1-a`

### Containers em produção (verificado 2026-06-25, 2ª sessão)

```
barbeariapro-app-backend    :8000   healthy   FastAPI   — git 3e138b5
barbeariapro-app-frontend   :3000   healthy   Next.js   — scp-deploy f5397a8
barbeariapro-postgres       :5432   healthy   Postgres  — migration HEAD: 0011_grant_crm_tables
evolution_api               :8080   Up        Evolution API v2.3.7 — instância Barbearia (open)
evolution_postgres          (interno)
evolution_redis             (interno)
n8n                         :5678   Up        n8n v2.27.3
```

### nginx (host da VM, não container)
- Instalado em `/etc/nginx/` — `systemctl enable nginx` (inicia no boot)
- Config: `/etc/nginx/sites-available/barbeariapro` → link em `sites-enabled/`
- Porta 80: `default_server` → `localhost:3000` (frontend)
- Porta 80 + `Host: api.taylorethedy.com` → `localhost:8000` (backend)
- **SSL/HTTPS**: pendente — domínio `taylorethedy.app` não registrado

### Acessos
- **App frontend:** `http://34.95.199.134` (porta 80 via nginx) ou `:3000` direto
- **App backend:** `http://34.95.199.134:8000`
- **n8n editor:** `http://34.95.199.134:5678` — login: `admin@barbearia.com` / `Barbearia2026`
- **Evolution manager:** `http://34.95.199.134:8080/manager`
- **Postgres (admin):** `docker exec barbeariapro-postgres psql -U postgres -d barbeariapro`
- **Página integrações (conectar WhatsApp):** `http://34.95.199.134:3000/admin/integracoes`

### Firewall (target-tag `http-server`)
`allow-evolution` (8080), `allow-n8n` (5678), `allow-backend` (8000), `allow-frontend` (3000), porta 80 aberta.
> ⚠️ Todas as portas abertas ao mundo. HTTPS ainda NÃO configurado (domínio não registrado).

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
| `/integracoes` | `app/api/integracoes.py` | JWT + público (callback OAuth) |

### Endpoints `/integracoes/*` (completos)
```
GET  /integracoes/google/calendar/status          — Google Calendar conectado?
GET  /integracoes/google/calendar/authorize-url   — URL OAuth Google (JSON)
GET  /integracoes/google/calendar/callback        — público, callback OAuth Google
GET  /integracoes/whatsapp/status                 — { connected: bool, phone: str|null }
GET  /integracoes/whatsapp/qr                     — { qr: "data:image/png;base64,..." }
```

### Endpoint `/bot/wa-webhook` — webhook proxy Evolution→FastAPI
`POST /bot/wa-webhook` — recebe eventos Evolution API:
- **`messages.upsert`** (fromMe=false): grava mensagem do cliente (`sender_type=client`) → SSE imediato
- **`send.message`**: evento para msgs enviadas pelo bot; grava como `sender_type=bot`; NÃO encaminha ao n8n
- Outros eventos: encaminhados ao n8n em background (retry 3× com backoff)
- Debug temporário: `print(f"[WA_WEBHOOK] event=...")` — **REMOVER** após confirmar `send.message`

### Endpoints `/crm/*` (JWT, conversations.py) — Inbox em tempo real
`GET /crm/conversations`, `GET /crm/conversations/search?q=`,
`GET /crm/conversations/{id}`, `GET /crm/conversations/{id}/messages`,
`PATCH /crm/conversations/{id}/read`,
`POST /crm/conversations/{id}/send` — envia mensagem pelo Inbox (via Evolution),
`GET /crm/stream?token=<jwt>` — **SSE em tempo real**.

---

## 7. Páginas do frontend (confirmadas no código — 15 rotas)

| Rota | Arquivo | Observação |
|---|---|---|
| `/login` | `app/login/page.tsx` | público |
| `/admin/dashboard` | `app/admin/dashboard/page.tsx` | |
| `/admin/agenda` | `app/admin/agenda/page.tsx` | |
| `/admin/clientes` | `app/admin/clientes/page.tsx` | |
| `/admin/crm` | `app/admin/crm/page.tsx` | toggle Kanban ⇄ Inbox; `?view=inbox` abre Inbox |
| `/admin/conversas` | `app/admin/conversas/page.tsx` | redirect server-side → `/admin/crm?view=inbox` |
| `/admin/financeiro` | `app/admin/financeiro/page.tsx` | |
| `/admin/servicos` | `app/admin/servicos/page.tsx` | |
| `/admin/equipe` | `app/admin/equipe/page.tsx` | |
| `/admin/fidelidade` | `app/admin/fidelidade/page.tsx` | placeholder "Em breve" |
| `/admin/campanhas` | `app/admin/campanhas/page.tsx` | placeholder "Em breve" |
| `/admin/empresa` | `app/admin/empresa/page.tsx` | placeholder "Em breve" |
| `/admin/usuarios` | `app/admin/usuarios/page.tsx` | placeholder "Em breve" |
| `/admin/integracoes` | `app/admin/integracoes/page.tsx` | **FUNCIONAL** — WhatsApp status + QR modal |
| `/admin/configuracoes` | `app/admin/configuracoes/page.tsx` | Google Calendar OAuth |
| `/barbeiro/agenda` | `app/barbeiro/agenda/page.tsx` | |

### Layout do admin (`app/admin/layout.tsx`)
Todas as rotas `/admin/*` usam `AdminShell` (sidebar + header).
- `components/layout/AdminSidebar.tsx` — colapsável (240px↔64px), localStorage `sb_nav_v1_collapsed`, mobile overlay, badges estáticos (Agenda:2, Conversas:5)
- `components/layout/AdminHeader.tsx` — breadcrumb dinâmico via `ROUTE_META`, notificação bell amber
- `components/layout/AdminShell.tsx` — compõe os dois, controla estado `mobileOpen`

### Design tokens (dark theme fixo — classe `dark` no `<html>`)
```
body: #0a0a0a | sidebar: #111111 | header: #0d0d0d
brand amber: #f59e0b | borders: #1a1a1a
active nav: rgba(245,158,11,0.11) + border-l-2 border-amber-500
```

---

## 8. Migrations Alembic

Head atual (verificado na VM): **`0011_grant_crm_tables`**.

```
0001_initial → 0002_loyalty → 0002_client_last_photo → 0003_client_photo_description
→ 0005_barber_services → 0006_client_blocked → 0007_crm_leads
→ 0008_client_bot_paused → 0009_conversation_log → 0010_conversations
→ 0011_grant_crm_tables  ← HEAD
```

> ⚠️ Migrations precisam de superuser postgres — `barber_app` não tem privilégio CREATE TYPE/TABLE.

---

## 9. Dados e usuários em PRODUÇÃO (VM, org_id = 1)

**Única organização:** `id=1` — "Barbearia Taylor e Thedy".

**Barbeiros ativos** (tabela `barbers`, `deleted_at IS NULL` — sem coluna `is_active`):

| id | name | specialty |
|---|---|---|
| 1 | Taylor | Cabeleireira e Barbeira |
| 2 | Thedy | Cabeleireiro e Barbeiro |
| 3 | Marciana | Cabeleireira e Manicure |
| 4 | Sandra | Cabeleireira e Designer de Sobrancelhas |
| 5 | Pablo | Barbeiro |

**Clientes reais:**
- `id=1` Augusto Pegoraro — `+556399368196` (8 dígitos — formato Evolution)
- `id=5` Reinaldo Viterbo — `+5563999789977`

> ⚠️ **Formato de telefone:** Evolution envia 8 dígitos (`556399368196@s.whatsapp.net`).
> `conv_id=1` tem `phone_e164 = '+556399368196'`. NÃO aplicar conversão 8→9 sem migrar o DB. Ver D-29.

**Roles do Postgres:** `barber_app` (RLS, senha `senha123`). Admin via `postgres`.

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
# + BOT_API_KEY, EVOLUTION_API_KEY, EVOLUTION_API_URL, OPENAI_API_KEY, POSTGRES_PASSWORD, SECRET_KEY
```

### Produção VM — `/opt/barbeariapro/.env.docker`
```
DATABASE_URL=postgresql+psycopg://barber_app:senha123@host.docker.internal:5432/barbeariapro
EVOLUTION_API_URL=http://host.docker.internal:8080
N8N_WEBHOOK_URL=http://host.docker.internal:5678
API_URL_INTERNAL=http://host.docker.internal:8000
AUTH_SECRET=<segredo>   AUTH_TRUST_HOST=true
```

---

## 11. Trava de disparo WhatsApp (crítica)

`app/services/whatsapp.py:15-21` — `send_text()` retorna `False` sem enviar nada
se `EVOLUTION_API_URL` **ou** `EVOLUTION_INSTANCE_NAME` estiverem vazios.

---

## 12. Bot WhatsApp / n8n (produção)

- **Evolution:** v2.3.7, instância **`Barbearia`** (B maiúsculo). WhatsApp pareado ao número `5563920001734`.
- **instanceId Evolution:** `6c3d8682-7d76-49cb-b0b4-e05893764c78` (recriada em 2026-06-25)
- **Webhook Evolution:** `http://host.docker.internal:8000/bot/wa-webhook` ← FASTAPI, não n8n
- **Eventos webhook:** `MESSAGES_UPSERT`, `MESSAGES_UPDATE`, `SEND_MESSAGE`, `CONNECTION_UPDATE`, `QRCODE_UPDATED`
- **n8n v2.27.3** — login: `admin@barbearia.com` / `Barbearia2026`
  - Campo de login: `emailOrLdapLoginId` (não `email`)
  - Atualizar workflow: `PATCH /rest/workflows/{id}` (não PUT — retorna 404)
- **Workflows ativos:** `BarbeariaPro Bot - WhatsApp Chatbot` (id `25QZQ664N6hrIg59`), `CronReminder24h01`, `CronReactivation1`
- **n8n workflow versionId:** `8ae50a30-49ac-4cd1-b290-e7e68bd89c25`
- **Persona:** "Raquel", GPT-4o-mini. Tools: `obter_perfil_cliente`, `cadastrar_cliente`, `listar_servicos`, `listar_barbeiros`, etc.
- **Barbeiros no system prompt:** Taylor(1), Thedy(2), Marciana(3), Sandra(4), Pablo(5)

### ⚠️ WhatsApp cai ao reiniciar a VM
A sessão WhatsApp se perde toda vez que a VM é reiniciada (ou fica TERMINATED).
Para reconectar: acessar `http://34.95.199.134:3000/admin/integracoes` e clicar em "Conectar WhatsApp".
Alternativa: `http://34.95.199.134:8080/manager` (Evolution Manager, QR auto-refresh).

### Reconectar via API (se a página não estiver acessível):
```bash
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command="
curl -s -X GET 'http://localhost:8080/instance/connect/Barbearia' \
  -H 'apikey: 6BCBCA57CE49-4E10-9C21-5B9FECAE40B2' | python3 -c '
import sys,json,base64; d=json.load(sys.stdin)
b64=d.get(\"base64\",\"\")
if b64:
    data=b64.replace(\"data:image/png;base64,\",\"\")
    open(\"/tmp/qr.png\",\"wb\").write(base64.b64decode(data))
    print(\"QR salvo em /tmp/qr.png\")
'"
# Copiar para local:
gcloud compute scp barbeariapro:/tmp/qr.png /tmp/qr_wa.png --project=barberiapro-app --zone=southamerica-east1-a
open /tmp/qr_wa.png
```

### Atualizar webhook Evolution após recriar instância:
```bash
curl -s -X POST http://localhost:8080/webhook/set/Barbearia \
  -H 'apikey: 6BCBCA57CE49-4E10-9C21-5B9FECAE40B2' \
  -H 'Content-Type: application/json' \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "http://host.docker.internal:8000/bot/wa-webhook",
      "byEvents": true, "base64": false,
      "events": ["MESSAGES_UPSERT","MESSAGES_UPDATE","SEND_MESSAGE","CONNECTION_UPDATE","QRCODE_UPDATED"]
    }
  }'
```

### Fluxo do bot (verificado na VM)
```
Webhook → Block List → Set Phone → IF Audio/Individual/Image
→ HTTP Debounce → IF Controller → Wait 5s → HTTP Flush Buffer
→ Code Horário Comercial  (Log Inbound DESABILITADO — ver D-30)
→ IF Horário Aberto → Send Composing → Wait → Composing Active
→ HTTP Check Bot Pause → IF Bot Paused
→ Memory → AI Agent → Send Response → Log Outbound Message
```

### Autenticação n8n (API REST)
```bash
curl -s -c /tmp/n8n_cookies -X POST 'http://localhost:5678/rest/login' \
  -H 'Content-Type: application/json' \
  -d '{"emailOrLdapLoginId":"admin@barbearia.com","password":"Barbearia2026"}'

# Atualizar workflow (PATCH, não PUT):
curl -sb /tmp/n8n_cookies -X PATCH \
  'http://localhost:5678/rest/workflows/25QZQ664N6hrIg59' \
  -H 'Content-Type: application/json' -d @/tmp/wf_payload.json
```

> ⚠️ D-14: NUNCA editar SQLite do n8n para workflows. SEMPRE via API REST.
> ⚠️ D-18: NUNCA conectar nós em paralelo. SEMPRE em série.
> ⚠️ D-35: Ao recriar instância Evolution, SEMPRE reconfigurar webhook para FastAPI (não n8n).

---

## 13. CRM Conversacional — arquitetura

### Fluxo completo de uma mensagem
```
WhatsApp → Evolution → POST /bot/wa-webhook → record_message(sender=client) → SSE → Inbox
                     ↓ (background, retry 3×)
                     n8n → debounce → AI Agent → Send Response (Evolution)
                                               → Log Outbound Message
                                                 → POST /bot/messages → record_message(sender=bot) → SSE → Inbox
```

> ⚠️ **Bot responses ainda não confirmadas no Inbox** (pendente desde 2026-06-24):
> debug `print [WA_WEBHOOK]` ativo nos logs do backend — remover após confirmar.

### Modelo de dados
- `conversations` — `UNIQUE(organization_id, phone_e164, channel)`
- `messages` — `sender_type`: `client|bot|human|system`; idempotência por `(conv_id, wa_message_id, sender_type)`
- `attachments` — FK `message_id` CASCADE

### Porta única de escrita: `app/services/conversation.py`
- `record_message` — idempotente; atualiza preview/unread; chama `_publish` após `flush()`
- SSE broker: `app/services/sse_broker.py` — single-process (asyncio)

---

## 14. Suíte de testes

```bash
docker start barbeariapro-staging-postgres
set -a; . ./.env.staging; set +a
export SEED_ORG_ID=1
.venv/bin/python -m pytest tests/ -q
```

**Baseline:** ~206 pass / 2 fail ambientais / 4 skip.
