# PROJECT_CONTEXT.md
> Fonte de verdade para novas sessões de desenvolvimento.
> Verificado contra o código E contra a VM de produção em **2026-06-23** (última atualização: sessão parte 5).

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
6. **Sincronização WhatsApp↔CRM implementada (parte 5)** — mensagens do bot agora
   aparecem no CRM em tempo real; CRM faz polling automático; nós de log no n8n
   gravados em série (ver §12, §8 e D-18). Pendente: teste de confirmação ao vivo.

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

**Estado git do backend (2026-06-23, após sessão parte 5):**
- Branch `main`, commits pushados até `4d4ed5e`.
- **VM está em `a11e0be`** (1 commit atrás): o commit `4d4ed5e` (n8n log nodes)
  não foi feito via git pull — o workflow foi atualizado diretamente pela API REST.
- `workflows.json` local **diverge da VM**: a versão local registra as conexões
  paralelas originais; a VM tem as conexões em SÉRIE (ver D-18, §12).
  Para sincronizar: exportar o workflow da VM via `GET /rest/workflows/25QZQ664N6hrIg59`
  e salvar como `workflows.json`.
- **`git pull` na VM agora funciona**: `safe.directory` configurado na sessão parte 5.
  Procedimento: `sudo git -C /opt/barbeariapro pull && docker compose -f docker-compose.app.yml up --build -d backend`

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
`GET /bot/clients/profile`, `GET /bot/clients/paused-status`,
`GET /bot/availability`, `POST /bot/appointments`,
`GET /bot/appointments`, `PATCH /bot/appointments/{id}/cancel`,
`PATCH /bot/appointments/{id}/complete`,
`POST /bot/messages` ← **novo (parte 5)**: grava mensagem inbound/outbound,
  atualiza `last_contact_at`, avança lead `novo_contato→conversando` no inbound;
  retorna `{"ok": false, "reason": "client_not_found"}` se o cliente não existe.

### Endpoints `/crm/*` (JWT)
`GET /crm/board`, `POST /crm/leads`, `GET /crm/leads/{id}`,
`PATCH /crm/leads/{id}`, `POST /crm/leads/{id}/move`, `DELETE /crm/leads/{id}`,
`GET /crm/leads/{id}/messages` ← **novo (parte 5)**: retorna histórico de conversa
  WhatsApp via `client_id` do lead (requires `body_text IS NOT NULL` em `message_log`).

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

Head atual (verificado na VM em 2026-06-23, parte 5): **`0009_conversation_log`**.

```
0001_initial → 0002_loyalty → 0002_client_last_photo → 0003_client_photo_description
→ 0005_barber_services → 0006_client_blocked → 0007_crm_leads
→ 0008_client_bot_paused → 0009_conversation_log  ← HEAD
```

`integration_accounts`, `calendar_sync` e `message_log` existem desde `0001_initial`.
- `0008_client_bot_paused` — coluna `bot_paused BOOLEAN` em `clients`
- `0009_conversation_log` — coluna `body_text TEXT` em `message_log` (parte 5)

> ⚠️ **Migrations 0008 e 0009 foram aplicadas via `ALTER TABLE` direto como postgres
> superuser** (não via `alembic upgrade`), porque `barber_app` não tem privilégio DDL.
> Forma correta: `docker exec barbeariapro-postgres psql -U postgres -d barbeariapro`

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

**Clientes reais cadastrados (verificado 2026-06-23 parte 5):**
- `id=1` Augusto Pegoraro — `+556399368196` (dono da conta)
- `id=5` Reinaldo Viterbo — `+5563999789977`

**Leads no Kanban (verificado 2026-06-23 parte 5):**
- `id=1` "Cliente Teste Funil" — estágio `agendado`, sem `client_id`
- `id=4` "Augusto Pegoraro" — estágio `novo_contato`, `client_id=1`
  (**criado manualmente**: o AI Agent criou o cliente antes do código de Lead
  existir; a lógica nova cria Lead automático para novos contatos)

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

### Fluxo principal do bot (2026-06-23 parte 5 — VERIFICADO NA VM)

```
Webhook → Block List → Set Phone → IF Is Audio / IF Individual / IF Has Image
→ HTTP Debounce → IF Controller → Wait 5s → HTTP Flush Buffer
→ Log Inbound Message          ← [NOVO parte 5] POST /bot/messages (direction=inbound)
→ Code Horário Comercial       ← usa $('HTTP Flush Buffer').first().json.* (refs explícitas)
→ IF Horário Aberto
→ Send Composing → Wait Typing Init → Send Composing Active
→ HTTP Check Bot Pause → IF Bot Paused
→ Memory → AI Agent (com tools abaixo)
→ Send Response
→ Log Outbound Message         ← [NOVO parte 5] POST /bot/messages (direction=outbound)
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

### Nós de Log (parte 5) — detalhes críticos
- **Tipo:** `n8n-nodes-base.httpRequest` v4.4, `onError: continueRegularOutput`
- **URL:** `http://host.docker.internal:8000/bot/messages`
- **Auth:** header `X-Bot-Token: ={{ $env.BOT_API_KEY }}`
- **Body format:** `specifyBody: "json"`, `jsonBody: "={{ {phone: ..., direction: ..., body: ...} }}"` — expressão que retorna OBJETO (não `JSON.stringify`)
- **Posição:** EM SÉRIE, não paralelo (ver D-18)
- **Log Inbound:** referencia `$('HTTP Flush Buffer').item.json.message`
- **Log Outbound:** referencia `$('AI Agent').item.json.output`

> ⚠️ **n8n é frágil — leia D-14 e D-18 antes de mexer.** NUNCA editar o SQLite direto.
> O `workflows.json` local diverge da VM; a fonte de verdade é a VM via API REST.

### Autenticação n8n (API REST)
Cookie de sessão expira. Para renovar:
```bash
# Na VM
python3 -c "
import json, urllib.request
body = json.dumps({'emailOrLdapLoginId': 'admin@barbeariapro.com', 'password': 'Barbearia2026'}).encode()
r = urllib.request.urlopen(urllib.request.Request('http://localhost:5678/rest/login', body, {'Content-Type': 'application/json'}))
print([h for h in r.headers.items() if 'set-cookie' in h[0].lower()])
"
# Salvar cookies em /tmp/n8n.cookies (formato netscape) para uso posterior
```

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
