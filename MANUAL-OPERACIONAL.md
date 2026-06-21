# Manual Operacional — BarbeariaPro

> **Escopo:** desenvolvimento, testes, homologação, implantação e rollback do
> ecossistema BarbeariaPro (API FastAPI + frontend Next + Postgres + n8n +
> Evolution/WhatsApp).
> **Princípio inegociável:** nenhuma rotina de desenvolvimento/teste pode
> sobrescrever dados de clientes reais nem disparar mensagens no WhatsApp de
> produção. As travas que garantem isso estão na Seção 2.

**Convenção de referências:** cada componente citado aponta o arquivo e a linha
reais (`arquivo:linha`). O que **não existe no código** está marcado como
**`NÃO CONFIRMADO`** — não foi assumido.

---

## 1. Visão geral da arquitetura

### 1.1 Componentes reais

| Componente | Onde está (real) | Observação |
|---|---|---|
| API FastAPI | `app/main.py:22` (`FastAPI(...)`) | uvicorn, porta 8000 |
| Routers da API | `app/main.py:32-45` (`include_router`) | ver tabela 1.2 |
| Config / variáveis | `app/core/config.py:10-49` (`Settings`) | lê `.env` (`config.py:12`) |
| Banco (RLS multi-tenant) | `schema.sql:369+` (`ENABLE ROW LEVEL SECURITY`), policies `tenant_isolation` | isolamento por organização |
| Sessão com tenant | `app/db/session.py:33` (`set_current_org` → `set_config('app.current_org_id')`) | aplica RLS por request |
| Auth do app (JWT) | `app/deps.py:43` (`get_tenant_db`), `app/api/auth.py:18` (`/auth`) | Bearer token |
| Auth do bot (n8n) | `app/deps.py:56` (`get_bot_db`, header `X-Bot-Token`) | usado pelos endpoints internos |
| Frontend Next | `barbearia-frontend/app/admin/*`, `barbearia-frontend/lib/api.ts:3` | porta 3000 |
| n8n (cérebro do bot) | `docker-compose.yml:57-78` (serviço `n8n`, container `n8n`, porta 5678) | workflow em `workflows.json` |
| Evolution (WhatsApp) | `docker-compose.yml:104-130` (serviço `evolution-api`, container `evolution_api`, porta 8080) | gateway WhatsApp |
| Envio de WhatsApp | `app/services/whatsapp.py:15` (`send_text` → POST `…/message/sendText/…` em `whatsapp.py:24`) | **trava de dry-run em `whatsapp.py:17`** |
| Postgres | `docker-compose.yml:33-51` (container `barbeariapro-postgres`, porta 5432) | roles `barber_owner`/`barber_app` |

### 1.2 Rotas da API (prefixos reais)

Registradas em `app/main.py:32-45`. Prefixos confirmados em cada router:

| Prefixo | Arquivo | Acesso |
|---|---|---|
| `/health` | `app/api/health.py:14` | público |
| `/auth` | `app/api/auth.py:18` | público (login) |
| `/bot` | `app/api/bot.py:40` | `X-Bot-Token` (`get_bot_db`) |
| `/loyalty` | `app/api/loyalty.py:18` | JWT |
| `/internal/loyalty` | `app/api/loyalty.py:19` | `X-Bot-Token` (`loyalty.py:20`) |
| `/internal/reminders` | `app/api/reminders.py:16` | `X-Bot-Token` (`reminders.py:13,17`) |
| `/agenda` | `app/api/agenda.py:35` | JWT |
| `/barbeiro` | `app/api/barbeiro.py:20` | JWT |
| `/financeiro` | `app/api/financeiro.py:35` | JWT |
| `/equipe` | `app/api/equipe.py:30` | JWT |
| `/clientes` | `app/api/clientes.py:21` | JWT |
| `/dashboard` | `app/api/dashboard.py:33` | JWT |
| `/dashboard/operacional` | `app/api/dashboard.py` (endpoint `get_operacional`) | JWT — métricas CRM/IA |
| `/servicos` | `app/api/servicos.py` | JWT |
| `/crm` | `app/api/crm.py:24` | JWT (funil/Kanban) |

### 1.3 Caminho de disparo de mensagens (superfície de risco)

```
n8n (cron / workflow)
   │  POST /internal/reminders  ou  /internal/loyalty   (header X-Bot-Token)
   ▼
app/api/reminders.py:27 (run_reminders)  /  app/api/loyalty.py:77 (run_reactivation)
   ▼
app/services/reminders.py:144  /  app/services/reactivation.py:125   → send_text(...)
   ▼
app/services/whatsapp.py:15 → POST {EVOLUTION_API_URL}/message/sendText/{INSTANCE}  (whatsapp.py:24)
   ▼
Evolution (container evolution_api, docker-compose.yml:104) → WhatsApp do cliente real
```

> **Esta é a cadeia que pode gerar disparo em massa.** Toda mudança que toque
> `reminders.py`, `reactivation.py`, `whatsapp.py` ou o workflow do n8n é
> classificada como risco **Crítico** (Seção 6).

### 1.4 Funil/CRM e métricas (entregues, em working tree)

- Tabelas `leads` / `lead_events` + enum `lead_stage`: `models/lead.py`, migration `alembic/versions/0007_crm_leads.py:17`.
- API do funil: `app/api/crm.py:24`.
- Métricas operacionais (leads/dia, serviços realizados, picos de demanda, fluxo comercial vs fora do horário): endpoint `get_operacional` em `app/api/dashboard.py`.

### 1.5 Itens do roadmap **NÃO CONFIRMADOS** no código

| Item | Situação real | Evidência |
|---|---|---|
| **Google Calendar (verificar disponibilidade / criar evento)** | Só **andaime** de dados; **sem** chamada à API do Google, OAuth ou worker | `models/integration.py:41` (`IntegrationAccount`), `:82` (`CalendarSync`), enum `google_calendar` em `models/enums.py:77`. Busca por `googleapis/oauth2/calendar.events` no código: **vazia** → **NÃO CONFIRMADO** |
| **Régua de follow-up 20min / 24h / 48h** | Existe apenas **um** lembrete único (`reminder_lead_hours`, default 24h) e reativação por cooldown | `app/services/reminders.py:75` (janela única), `config.py:48-49`; reativação em `app/services/reactivation.py:39`. Multi-estágio 20/24/48: **NÃO CONFIRMADO** |
| **Gestão de objeções (prompt da IA)** | Vive no **workflow do n8n** (`workflows.json`), não no código Python | `workflows.json` (artefato); prompt não versionado como código → **NÃO CONFIRMADO no código-fonte** |
| **Automação de status no CRM via Calendar** | Depende de Calendar (acima) | `lead_events` já suporta histórico (`models/lead.py`), mas o gatilho automático **NÃO CONFIRMADO** |

---

## 2. Ambientes e travas de isolamento

### 2.1 Os três ambientes

| Ambiente | Banco | API | Frontend | n8n / Evolution |
|---|---|---|---|---|
| **Local** | Postgres local ou staging (5433) | uvicorn no host (8000) | `next dev` (3000) | normalmente desligados |
| **Staging** | `barbeariapro-staging-postgres` **porta 5433** (container isolado) | uvicorn/back container apontando p/ 5433 | build local | n8n/Evolution **de teste** (ver 2.3) |
| **Produção** | `barbeariapro-postgres` **5432** | `barbeariapro-app-backend` (8000) | `barbeariapro-app-frontend` (3000) | `n8n` (5678) + `evolution_api` (8080) |

Composes reais: infra em `docker-compose.yml` (project default), app em
`docker-compose.app.yml:15` (`name: barbeariapro-app`). Redes distintas:
`barbearia_network`, `barbearia-whatsapp_default`, `barbeariapro-app_default`.

### 2.2 🔒 Trava nº 1 — a mais importante (dry-run nativo de WhatsApp)

`app/services/whatsapp.py:17` curto-circuita o envio quando as variáveis da
Evolution estão vazias:

```python
# app/services/whatsapp.py:15-17
async def send_text(phone: str, message: str) -> bool:
    if not settings.evolution_api_url or not settings.evolution_instance_name:
        # não envia nada
```

**Regra operacional:** em **Local e Staging**, deixe `EVOLUTION_API_URL` e
`EVOLUTION_INSTANCE_NAME` **vazios** (ou apontando para instância de teste).
Vazios = `send_text` retorna sem tocar o WhatsApp. Essas variáveis são lidas em
`app/core/config.py:39-41`.

### 2.3 Variáveis/arquivos reais que DEVEM diferir em Staging

A aplicação lê estas variáveis em `app/core/config.py`. O staging usa o arquivo
`.env.staging` (gitignored, já existente) com a porta do banco trocada para 5433.

| Variável (`config.py`) | Produção | Staging (obrigatório) | Por quê |
|---|---|---|---|
| `DATABASE_URL` (`:22`) | `…@localhost:5432/barbeariapro` | `…@localhost:5433/barbeariapro` | banco fictício isolado; **nunca** apontar Staging p/ 5432 |
| `EVOLUTION_API_URL` (`:39`) | `http://localhost:8080` | **vazio** ou Evolution de teste | trava 2.2 — sem isso, dispara no WhatsApp real |
| `EVOLUTION_INSTANCE_NAME` (`:40`) | instância real | **vazio** ou `barbearia_teste` | idem |
| `EVOLUTION_API_KEY` (`:41`) | chave real | chave de teste/qualquer | impede usar credencial de produção |
| `BOT_API_KEY` (`:34`) | chave real | **chave diferente** | impede n8n de prod acionar Staging e vice-versa (auth em `app/deps.py:60`) |
| `BOT_ORGANIZATION_ID` / `BOT_UNIT_ID` (`:35-36`) | org/unidade reais | org/unidade **fictícias** | `get_bot_db` (`deps.py:65`) escopa o tenant do bot |
| `OPENAI_API_KEY` (infra, `docker-compose.yml:71`) | chave real | chave de teste/throwaway | evita custo/efeito em prod |

> ⚠️ **PARADA DE SEGURANÇA (Regra de Ouro):** nunca copie o `.env` de produção
> para Staging "só pra funcionar". Se `DATABASE_URL` de Staging apontar para
> `:5432`, qualquer teste sobrescreve clientes reais; se `EVOLUTION_API_URL`
> apontar para o gateway real, qualquer execução de `reminders`/`reactivation`
> dispara WhatsApp em massa. **Sempre gere `.env.staging` derivando do `.env` e
> trocando porta + zerando Evolution** (ver Seção 3).

### 2.4 🔒 Trava nº 2 — isolamento de banco (RLS)

Todo acesso do app passa por `set_current_org` (`app/db/session.py:33`), e as
policies `tenant_isolation` (`schema.sql:384+`) filtram por
`current_setting('app.current_org_id')`. A role do app (`barber_app`) é
`NOBYPASSRLS`. **Mesmo assim isso não substitui a separação física de banco** —
Staging deve ser um banco diferente (5433), não a mesma base com outra org.

### 2.5 🔒 Trava nº 3 — n8n e Google Calendar separados

- **n8n:** o container de produção é `n8n` (`docker-compose.yml:58`) com volume
  `n8n_data`. Staging deve usar uma **instância n8n separada** (outro container +
  outro volume), com `EVOLUTION_API_KEY`/`BOT_API_KEY` de teste, para que os
  workflows de Staging **não publiquem** no Evolution de produção. Importação de
  workflow é manual (`docker-compose.yml:24-25`).
- **Google Calendar:** como o worker é **NÃO CONFIRMADO** (Seção 1.5), não há
  escrita automática em agenda hoje. Quando existir, a trava é **não ter tokens
  reais** em Staging: a tabela `integration_accounts` (`models/integration.py:41`,
  coluna `token_encrypted:60`) deve ficar **vazia** em Staging.

---

## 3. Configuração do ambiente de desenvolvimento

### 3.1 Pré-requisitos
- Docker + Compose v2; Python 3.12 (venv); Node 20 (frontend).
- Repos: `barbeariapro` (backend/infra) e `barbearia-frontend` (Next).

### 3.2 Subir o banco de Staging (isolado, porta 5433)
Banco de testes **separado** do de produção (`barbeariapro-postgres:5432`):

```bash
docker run -d --name barbeariapro-staging-postgres \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=postgres \
  -p 5433:5432 postgres:16
```

> O dump de produção é **somente leitura** (`pg_dump`/`pg_dumpall`) e nunca
> escreve em 5432. Restaure no 5433. Para dados **fictícios** (preferível p/
> LGPD), use `scripts/seed.py` em vez de copiar PII real.

### 3.3 Gerar `.env.staging` com as travas (derivado do `.env`)

```bash
# troca a porta do banco 5432 -> 5433 e ZERA a Evolution (trava 2.2)
sed -E 's/@localhost:5432/@localhost:5433/g' .env > .env.staging
# garanta manualmente no .env.staging:
#   EVOLUTION_API_URL=        (vazio)
#   EVOLUTION_INSTANCE_NAME=  (vazio)
#   BOT_API_KEY=staging-key-diferente
```

### 3.4 Migrations e seed (no Staging)
O Alembic lê `DATABASE_URL` do ambiente (`alembic/env.py:31`). **Sempre exporte a
URL de Staging** ao rodar migrations fora de produção:

```bash
export STG="postgresql+psycopg://barber_owner:<senha>@localhost:5433/barbeariapro"
DATABASE_URL="$STG" .venv/bin/python -m alembic upgrade head   # head = 0007_crm_leads
DATABASE_URL="$STG" .venv/bin/python scripts/seed.py           # org fictícia + grants
```
> Nota: o console-script `alembic` pode ter shebang quebrado se a venv foi movida;
> use `python -m alembic`. Cadeia de migrations termina em
> `alembic/versions/0007_crm_leads.py:17` (`down_revision = 0006_client_blocked`).

### 3.5 Rodar a API e os testes contra Staging
```bash
DATABASE_URL="$STG" .venv/bin/python -m uvicorn app.main:app --port 8001
DATABASE_URL="$STG" .venv/bin/python -m pytest tests/ -q
```
> Os testes de integração rodam o app ASGI **contra o banco de `DATABASE_URL`**
> (`tests/conftest.py:30`) e autenticam no owner semeado da org 3
> (`conftest.py:18-20`). **Se `DATABASE_URL` apontar para 5432, os testes mutam
> produção.** Sempre exporte a URL de Staging.

### 3.6 Frontend
`barbearia-frontend/lib/api.ts:3` usa `NEXT_PUBLIC_API_URL` (browser) e
`API_URL_INTERNAL` (SSR). Em dev: `npm run dev` (porta 3000).

---

## 4. Fluxo de trabalho de desenvolvimento

```
Branch → Local → Staging → Validação → Produção
```

### 4.1 Branch
- Criar branch a partir de `main`. Nunca desenvolver direto na `main`.
- Checklist: [ ] branch criada · [ ] escopo definido · [ ] toca caminho de disparo (Seção 1.3)? se sim, marcar risco Crítico.

### 4.2 Local
- Implementar; rodar `pytest` contra **Staging (5433)**; `tsc --noEmit` no frontend.
- Checklist: [ ] testes passam · [ ] `EVOLUTION_API_URL` vazio no `.env` local · [ ] nenhuma migration aplicada em 5432.

### 4.3 Staging
- `alembic upgrade head` + `seed.py` no 5433; subir uvicorn (8001) e frontend.
- Validar via HTTP **no banco de Staging**.
- Checklist: [ ] migration aditiva (não destrói coluna/tabela existente) · [ ] Evolution de Staging vazia/teste · [ ] suíte completa verde.

### 4.4 Validação / Homologação
- Rodar o Checklist de Homologação (Seção 10.1).
- Checklist: [ ] fluxo E2E do módulo OK · [ ] sem disparo real observado · [ ] risco classificado (Seção 6).

### 4.5 Produção
- **Somente com sua autorização.** Backup do banco antes (Seção 7.2).
- Checklist: ver Checklist de Deploy (Seção 10.2).

---

## 5. Estratégia de testes

### 5.1 O que já existe (real)
- Suíte de integração ASGI: `tests/` (ex.: `tests/test_clientes_integration.py`,
  `tests/test_crm_integration.py`, `tests/test_dashboard_operacional.py`,
  `tests/test_e2e_flow.py`), fixtures em `tests/conftest.py`.
- Testes unitários puros (sem rede): ex. `tests/test_bot_unit.py`.

### 5.2 Por módulo

| Módulo | Unitário | Integração | E2E / segurança |
|---|---|---|---|
| **Bot** | normalização/telefone, debounce (`app/api/bot.py:40`+, `tests/test_bot_unit.py`) | endpoints `/bot` com `X-Bot-Token` | **sem** disparo: ver 5.3 |
| **IA (n8n)** | **NÃO CONFIRMADO** no código (prompt vive no `workflows.json`) | testar workflow em n8n **de teste** | nunca apontar p/ Evolution de prod |
| **Follow-up / lembrete** | `build_message`/`idempotency_key` (`reminders.py:42,47`) puros | `/internal/reminders` com banco Staging | **send_text neutralizado** (5.3) |
| **CRM** | validações de schema (`app/api/crm.py`) | `tests/test_crm_integration.py` (11 casos) | RLS por org |
| **Dashboard/métricas** | helpers de data (`app/core/dates.py`) | `tests/test_dashboard_operacional.py` (4 casos) | somente leitura |

### 5.3 Testar n8n/WhatsApp **sem disparo real** (métodos viáveis no projeto)

1. **Dry-run nativo (recomendado):** deixar `EVOLUTION_API_URL`/
   `EVOLUTION_INSTANCE_NAME` vazios — `app/services/whatsapp.py:17` impede o POST.
   `send_text` retorna sem enviar; o resto do fluxo (idempotência, `message_log`)
   continua testável.
2. **Idempotência:** `reminders.py:42` (`idempotency_key`) + coluna única
   `message_log.idempotency_key` (`models/integration.py:161`) evitam reenvio.
   Teste reexecutando o endpoint e verificando que não duplica.
3. **Número de teste isolado:** se precisar testar o POST real, use uma
   **instância Evolution de teste** com um **chip de teste**, nunca a instância de
   produção. Configurar em `.env.staging` (Seção 2.3).
4. **n8n de teste:** instância separada (Seção 2.5) com `BOT_API_KEY` de teste —
   o `/internal/*` exige o token (`app/deps.py:60`), então o n8n de prod não
   aciona o backend de Staging.

> 🚫 **NÃO** rode o caminho de `reminders`/`reactivation` apontando para a
> Evolution de produção "só para ver se funciona". Isso é disparo real em
> clientes. Use o dry-run (item 1).

---

## 6. Classificação de risco das funcionalidades

| Nível | Funcionalidade | Evidência | Por quê |
|---|---|---|---|
| **CRÍTICO** | Envio de WhatsApp (lembrete/reativação) | `reminders.py:144`, `reactivation.py:125`, `whatsapp.py:24` | disparo em massa a clientes reais |
| **CRÍTICO** | Edição do workflow do n8n | `workflows.json`, `docker-compose.yml:58` | pode derrubar o atendimento ativo ou disparar errado |
| **CRÍTICO** | Migrations destrutivas em produção | `alembic/versions/*`, banco `barbeariapro-postgres:5432` | perda/corrupção de dados de clientes |
| **CRÍTICO** | Google Calendar — escrita de evento | **NÃO CONFIRMADO** (`models/integration.py:82`) | quando existir, altera agenda real |
| **ALTO** | Endpoints do bot `/bot`, `/internal/*` | `app/api/bot.py:40`, `reminders.py:16`, `loyalty.py:19` | acionam lógica de mensagem; auth por token |
| **ALTO** | Migrations aditivas em produção | `0007_crm_leads.py` | mudança de schema, ainda que aditiva |
| **MÉDIO** | Mutação no CRM (`/crm`) | `app/api/crm.py:24` | escreve `leads` (tabelas novas isoladas), sem tocar `clients` |
| **MÉDIO** | Alteração de `clientes`/`agenda`/`financeiro` | `app/api/clientes.py:21`, `agenda.py:35` | grava dados de negócio reais |
| **BAIXO** | Leitura de dashboard/métricas | `app/api/dashboard.py:33`, `get_operacional` | somente SELECT |
| **BAIXO** | `/health`, `/health/db` | `app/api/health.py:14` | sem efeito colateral |

---

## 7. Implantação (Deploy)

### 7.1 Topologia de produção (real)
- App: `docker-compose.app.yml` (project `barbeariapro-app:15`), serviços
  `backend` (8000) e `frontend` (3000).
- Infra (NÃO redeployar junto): `docker-compose.yml` (`barbeariapro-postgres`,
  `n8n`, `evolution_api`).

### 7.2 Backup obrigatório antes de qualquer deploy que toque o banco
```bash
docker exec barbeariapro-postgres pg_dump -U postgres barbeariapro > backup-$(date +%Y%m%d-%H%M).sql
```
> ⚠️ **PARADA (Regra de Ouro):** este manual **não** manda você executar deploy em
> produção automaticamente. Qualquer comando que toque a infra viva (subir
> container de prod, rodar migration em 5432, importar workflow no n8n) exige
> **autorização explícita** e janela combinada.

### 7.3 Deploy por tipo de mudança
- **Pequena (BAIXO/MÉDIO, sem migration):**
  `docker compose -f docker-compose.app.yml up -d --build` (recria só o que mudou).
- **Média (com migration aditiva):** backup (7.2) → `alembic upgrade head` em prod
  (autorizado) → `seed.py` se a migration adicionou tabela (reaplica grants
  `barber_app`) → `up -d --build`.
- **Crítica (toca disparo/n8n/Calendar):** janela de manutenção + acompanhamento +
  plano de rollback pronto (Seção 8) **antes** de iniciar.

---

## 8. Rollback e recuperação

### 8.1 Por componente

| Componente | Rollback imediato |
|---|---|
| **App (backend/frontend)** | `docker compose -f docker-compose.app.yml up -d` apontando para a **imagem anterior** (tag/commit prévio); containers usam `restart: unless-stopped` |
| **Migration** | `DATABASE_URL=<prod> python -m alembic downgrade <revisão anterior>` — só se o `downgrade()` for seguro (a `0007` tem downgrade que **dropa** `leads`/`lead_events`: revisar antes) |
| **Banco (dados)** | restaurar o dump de 7.2: `cat backup.sql \| docker exec -i barbeariapro-postgres psql -U postgres -d barbeariapro` |
| **n8n (workflow)** | reimportar a versão anterior do `workflows.json` (há backups: `workflows-backup*.json`) e republicar (`docker-compose.yml:24-25`) |
| **Evolution/WhatsApp** | desligar disparo: **zerar `EVOLUTION_API_URL`** e reiniciar o backend (trava 2.2) interrompe envios imediatamente |

### 8.2 "Botão de freio" de disparo
Se um follow-up errado começar a disparar: zere `EVOLUTION_API_URL` no ambiente
do backend e reinicie — `whatsapp.py:17` passa a curto-circuitar todos os envios.

---

## 9. Monitoramento pós-deploy

### 9.1 Saúde imediata
```bash
curl http://localhost:8000/health        # {"status":"ok"}
curl http://localhost:8000/health/db      # {"database":"reachable"}  (app/api/health.py)
curl -i http://localhost:3000             # 307 -> /login
docker ps                                  # 7 containers Up (app healthy)
```

### 9.2 Métricas de negócio (já disponíveis)
- `GET /dashboard` (`app/api/dashboard.py:33`): receita, ocupação, conversão.
- `GET /dashboard/operacional` (`get_operacional`): leads/dia, serviços
  realizados, **picos de demanda**, **fluxo comercial vs fora do horário**.

### 9.3 Sinais de disparo de mensagens
- Tabela `message_log` (`models/integration.py:130`): `delivery_status`,
  `attempt_count`, `idempotency_key`. Picos anômalos de `outbound` =
  investigar imediatamente (possível follow-up em massa).
- Logs do `n8n` (`docker compose logs n8n`) e do backend
  (`docker compose -f docker-compose.app.yml logs backend`).

### 9.4 Bot vivo
`docker exec n8n sh -c "wget -q -O - http://host.docker.internal:8000/health"` →
confirma que o n8n alcança a API (caminho do bot).

---

## 10. Checklists operacionais

### 10.1 ✅ Homologação (antes de aprovar para produção)
- [ ] Rodando contra **Staging (5433)**, nunca 5432.
- [ ] `EVOLUTION_API_URL`/`EVOLUTION_INSTANCE_NAME` vazios ou de teste (trava 2.2).
- [ ] `BOT_API_KEY` de Staging diferente do de produção.
- [ ] Suíte `pytest tests/` 100% verde no Staging.
- [ ] `tsc --noEmit` e `next build` sem erro (se mexeu no frontend).
- [ ] Migration revisada como **aditiva** (sem `DROP`/`ALTER` destrutivo em tabela existente).
- [ ] Fluxo E2E do módulo validado **sem disparo real** observado em `message_log`.
- [ ] Risco classificado (Seção 6) e registrado no PR.

### 10.2 ✅ Deploy (produção)
- [ ] **Autorização explícita** recebida + janela combinada (itens Crítico).
- [ ] Backup do banco feito (Seção 7.2) e **verificado**.
- [ ] Plano de rollback escrito e à mão (Seção 8).
- [ ] `EVOLUTION_API_URL` de produção confirmado (não foi sobrescrito por engano).
- [ ] Deploy do app: `docker compose -f docker-compose.app.yml up -d --build`.
- [ ] Migration (se houver): `alembic upgrade head` + `seed.py` (grants).
- [ ] Pós-deploy: `/health`, `/health/db`, `docker ps`, bot alcança API (9.4).
- [ ] Infra (`postgres`/`n8n`/`evolution`) **intacta** — uptime inalterado.

### 10.3 ✅ Rollback (quando algo deu errado)
- [ ] Identificado o componente afetado (app / migration / dados / n8n / WhatsApp).
- [ ] Se disparo indevido: **zerar `EVOLUTION_API_URL` + reiniciar backend** (freio 8.2).
- [ ] App: subir imagem/commit anterior (8.1).
- [ ] Migration: `alembic downgrade` **só** se o downgrade for seguro; senão restaurar dump.
- [ ] Dados: restaurar backup (8.1) — confirmar contagem de clientes pós-restore.
- [ ] n8n: reimportar `workflows-backup*.json` e republicar.
- [ ] Validar saúde (Seção 9) e comunicar.

### 10.4 ✅ Auditoria mensal
- [ ] Conferir que `.env.staging` ainda aponta para 5433 e Evolution vazia/teste.
- [ ] Revisar `message_log` do mês: volume de `outbound`, falhas, picos anômalos.
- [ ] Conferir que nenhuma credencial de produção vazou para Staging/local.
- [ ] Revisar acessos: roles `barber_app`/`barber_owner`, RLS ativa (`schema.sql:369+`).
- [ ] Testar restauração de backup num banco descartável (ensaio de rollback).
- [ ] Revisar itens **NÃO CONFIRMADOS** (Seção 1.5): se algum foi implementado,
      reclassificar risco (Seção 6) e atualizar este manual.
- [ ] Conferir uptime/saúde dos 7 containers e do caminho do bot (9.4).

---

### Apêndice — itens marcados NÃO CONFIRMADO (não inventar)
Os seguintes itens do roadmap **não têm implementação no código** na data desta
análise; qualquer instrução sobre eles é de **arquitetura futura**, não de
operação atual:
- Worker/OAuth do **Google Calendar** (só andaime: `models/integration.py:41,82`).
- **Régua de follow-up 20min/24h/48h** (existe lembrete único: `reminders.py:75`).
- **Prompt de gestão de objeções** (vive no `workflows.json` do n8n, não no código).
- **Automação de status CRM via Calendar** (depende dos itens acima).
