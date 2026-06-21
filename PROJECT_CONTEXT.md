# PROJECT_CONTEXT.md
> Fonte de verdade para novas sessões de desenvolvimento. Verificado contra o código em 2026-06-21.

---

## 1. O que é o projeto

**BarbeariaPro** — plataforma SaaS de gestão para barbearias e salões.
Produto atual: uma barbearia âncora (produção ativa, clientes reais).
Objetivo comercial: vender para mais barbearias; concorre com Trinks (análise em `ROADMAP_IMPLEMENTACAO.md`).

---

## 2. Repositórios e estrutura de arquivos

| Repo / Diretório | Branch principal | Conteúdo |
|---|---|---|
| `/Users/apleandro/dev/barbeariapro` | `main` | Backend FastAPI + infra Docker |
| `/Users/apleandro/dev/barbeariapro/barbearia-frontend` | `main` | Frontend Next.js (repo git separado dentro do diretório) |

> **Atenção:** `barbearia-frontend/` é um sub-repositório git independente.
> Commits de backend e frontend são feitos separadamente.

Branch de desenvolvimento ativo: `feat/fase2-google-calendar` (backend).
PR aberto: https://github.com/augustopegoraro-droid/barbeariapro/pull/1

---

## 3. Stack tecnológica

### Backend
- **Python 3.9**, FastAPI, SQLAlchemy async (psycopg3), Alembic
- **PostgreSQL 16** com Row Level Security (multi-tenant por `organization_id`)
- Autenticação: JWT Bearer (`app/core/security.py`) + `X-Bot-Token` para o bot
- Criptografia de tokens OAuth: Fernet (`app/core/crypto.py`)
- Venv: `.venv/` na raiz do backend

### Frontend
- **Next.js** (versão nova — leia `barbearia-frontend/AGENTS.md` antes de mexer)
- next-auth para sessão JWT
- Tailwind CSS, Axios (`barbearia-frontend/lib/api.ts`)

### Infraestrutura
- **Docker Compose** — dois composes:
  - `docker-compose.yml`: infra (Postgres prod `:5432`, n8n `:5678`, Evolution `:8080`)
  - `docker-compose.app.yml`: app (backend `:8000`, frontend `:3000`)
- Staging: container avulso `barbeariapro-staging-postgres` na porta `:5433`

---

## 4. Ambientes

| Ambiente | Banco | API | Frontend | WhatsApp |
|---|---|---|---|---|
| **Produção** | `barbeariapro-postgres:5432` | container `:8000` | container `:3000` | Evolution ativo |
| **Staging** | `barbeariapro-staging-postgres:5433` | uvicorn local `:8001` | `next dev` `:3000` | Evolution **vazio** (dry-run) |

### Como subir staging
```bash
# 1. Garantir container rodando
docker start barbeariapro-staging-postgres

# 2. Carregar variáveis e rodar API
set -a; . ./.env.staging; set +a
.venv/bin/python -m uvicorn app.main:app --port 8001

# 3. Rodar suíte de testes
export SEED_ORG_ID=1
.venv/bin/python -m pytest tests/ -q
# Resultado esperado: 206 pass / 2 fail ambientais / 4 skip
```

### Regra de Ouro (inviolável)
- `EVOLUTION_API_URL` e `EVOLUTION_INSTANCE_NAME` **VAZIOS** em staging e local.
- `DATABASE_URL` de staging aponta para `:5433`, nunca `:5432`.
- Detalhes em `MANUAL-OPERACIONAL.md` Seção 2.

---

## 5. Rotas da API (confirmadas no código)

| Prefixo | Arquivo | Auth |
|---|---|---|
| `/health` | `app/api/health.py` | público |
| `/auth` | `app/api/auth.py` | público (login) |
| `/bot` | `app/api/bot.py` | `X-Bot-Token` |
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
| `/integracoes` | `app/api/integracoes.py` | JWT (authorize/status/url) + público (callback) |

Total atual: **67 rotas** (`len(app.routes)`).

---

## 6. Páginas do frontend (confirmadas no código)

| Rota | Arquivo | Quem usa |
|---|---|---|
| `/login` | `app/login/page.tsx` | todos |
| `/admin/agenda` | `app/admin/agenda/page.tsx` | owner/manager/recepção |
| `/admin/clientes` | `app/admin/clientes/page.tsx` | owner/manager/recepção |
| `/admin/dashboard` | `app/admin/dashboard/page.tsx` | owner/manager |
| `/admin/equipe` | `app/admin/equipe/page.tsx` | owner/manager |
| `/admin/financeiro` | `app/admin/financeiro/page.tsx` | owner/manager |
| `/admin/servicos` | `app/admin/servicos/page.tsx` | owner/manager |
| `/admin/crm` | `app/admin/crm/page.tsx` | owner/manager |
| `/admin/configuracoes` | `app/admin/configuracoes/page.tsx` | owner/manager |
| `/barbeiro/agenda` | `app/barbeiro/agenda/page.tsx` | barbeiro (mobile-first) |

---

## 7. Migrations Alembic (estado em produção)

Head atual: **`0007_crm_leads`** (aplicada em produção em 2026-06-16).

```
0001_initial → 0002_loyalty → 0002_client_last_photo → 0003_client_photo_description
→ 0005_barber_services → 0006_client_blocked → 0007_crm_leads  ← HEAD
```

`integration_accounts`, `calendar_sync` e `message_log` já existem desde `0001_initial`.
**Nenhuma migration nova foi necessária para a Fase 2.**

---

## 8. Usuários semeados (staging org_id=1)

| Email | Role | Senha |
|---|---|---|
| `taylor@barbeariapro.com` | owner | `senha123` |
| `thedy@barbeariapro.com` | owner | `senha123` |
| `marciana@barbeariapro.com` | barber | `senha123` |
| `sandra@barbeariapro.com` | barber | `senha123` |
| `pablo@barbeariapro.com` | barber | `senha123` |

**Staging:** `SEED_ORG_ID=1` (banco novo). Produção usa org_id=3.
Dois testes hardcoded na org 3 ficam com fail ambiental — é esperado.

---

## 9. Variáveis de ambiente críticas (`.env.staging`)

```
DATABASE_URL=postgresql+psycopg://barber_app:senha123@localhost:5433/barbeariapro
EVOLUTION_API_URL=          # VAZIO — trava de dry-run
EVOLUTION_INSTANCE_NAME=    # VAZIO — trava de dry-run
BOT_API_KEY=staging-bot-key-isolada-fase2
GOOGLE_CLIENT_ID=<ver .env.staging — OAuth Client criado no Google Cloud Console>
GOOGLE_CLIENT_SECRET=<ver .env.staging — OAuth Client criado no Google Cloud Console>
GOOGLE_REDIRECT_URI=http://localhost:8001/integracoes/google/calendar/callback
TOKEN_ENCRYPTION_KEY=<ver .env.staging — gerado com Fernet.generate_key()>
GOOGLE_FRONTEND_SUCCESS_URL=http://localhost:3000/admin/configuracoes
```

> Valores reais ficam apenas no `.env.staging` (gitignored). O OAuth Client está
> no Google Cloud Console do projeto BarbeariaPro.

> O arquivo `.env.staging` está no gitignore — não é versionado. Variáveis acima
> são de staging/teste. Nunca copiar para produção.

---

## 10. Trava de disparo WhatsApp (crítica)

`app/services/whatsapp.py:15-17` — se `EVOLUTION_API_URL` ou `EVOLUTION_INSTANCE_NAME`
estiverem vazios, `send_text()` retorna sem enviar nada.
Esta é a principal barreira entre testes e disparo real em produção.

---

## 11. Suíte de testes

```bash
# Staging obrigatório (container na 5433):
docker start barbeariapro-staging-postgres
set -a; . ./.env.staging; set +a
export SEED_ORG_ID=1
.venv/bin/python -m pytest tests/ -q
```

**Resultado baseline:** 206 pass / 2 fail ambientais / 4 skip  
Fails conhecidos (NÃO são bugs):
- `test_me_isola_tenant_via_rls` — hardcode `assert organization_id == 3` (staging é org 1)
- `test_login_cria_cliente_cria_agendamento` — hardcode `barber_id=1/service_id=6` (seed diferente)

Skips: testes de worker que precisam de agendamentos no staging (banco vazio).
