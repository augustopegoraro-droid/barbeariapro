# CURRENT_SPRINT.md
> Estado do desenvolvimento em **2026-06-23**. Atualizar a cada sessão.

---

## Branch ativo

`main` (backend) — em dia com `origin/main` (todos os commits pushados).

---

## ✅ Sessão 2026-06-23 — parte 1: restauração da VM de produção

A VM de produção foi encontrada **completamente zerada**. Toda a stack foi reconstruída do zero.

| Item | Detalhe |
|---|---|
| Docker instalado na VM | `curl -fsSL https://get.docker.com \| sudo sh` |
| Stack infra remontada | postgres + n8n + evolution (api/postgres/redis) via `docker-compose.yml` |
| Stack app remontada | backend `:8000` + frontend `:3000` via `docker-compose.app.yml` |
| Banco recriado | role `barber_app` criado à mão, migrations (`0007_crm_leads`), seed org 1 |
| WhatsApp pareado | número `5563920001734`, instância Evolution `Barbearia` |
| Workflows n8n importados e ativos | bot + 2 crons |
| **Bot funcionando end-to-end** | conversa + agendamento confirmados por teste real |
| Login n8n restaurado | `admin@barbeariapro.com` / `Barbearia2026` (bcrypt resetado via Python) |
| Credencial OpenAI corrigida | recriada via **API REST do n8n** (ver D-14) |
| Fix bug de disponibilidade | GPT-4o-mini dizia "horário reservado" para slot livre → instrução nova no system prompt (ver D-15) |

---

## ✅ Sessão 2026-06-23 — parte 4: bot responde fora do horário

**Mudança:** bot passa a atender 24/7, mas avisa quando a barbearia está fechada.

- `IF Horário Aberto`: ramo `false` agora vai para `Send Composing` (igual ao `true`)
  — antes encerrava em `Send Offline Message`
- `Code Horário Comercial`: adiciona prefixo `[FORA_DO_HORARIO]` na mensagem
  quando fora do expediente; removido `BYPASS_HOURS` desnecessário
- System prompt: Raquel informa horário de funcionamento (seg-sex 9h-19h, sáb 9h-17h)
  quando detecta `[FORA_DO_HORARIO]`, mas continua agendando e respondendo perguntas
- Commit `7464def`, workflow n8n atualizado (versionId `7519aa44`)

---

## ✅ Sessão 2026-06-23 — parte 3: funil completo + pausa do bot via CRM

### Funil para clientes existentes + pausa do bot

**Problema reportado:** clientes antigos que voltam a mandar mensagem não entravam
no funil; equipe não tinha como pausar o bot para assumir o atendimento manualmente.

**Correções (commit `4721316`):**

- `bot.py — upsert_client`: clientes existentes sem lead ativo nos últimos 7 dias
  também recebem um novo lead em `novo_contato` quando contatam via WhatsApp.
- `bot.py — GET /bot/clients/paused-status?phone=X`: retorna `{"paused": bool}`;
  usado pelo n8n antes de chamar o AI Agent.
- `clientes.py — PATCH /clientes/{id}/bot-pause?paused=bool`: endpoint JWT para
  staff pausar/retomar o bot por cliente.
- `crm.py — GET /crm/board`: passa a incluir `bot_paused` do cliente vinculado
  ao lead (join com `clients`).
- `alembic/0008_client_bot_paused.py`: migration formal (coluna já existia em
  produção por ALTER TABLE direto).
- `workflows.json`: dois novos nós inseridos entre `Send Composing Active` e
  `AI Agent` — `HTTP Check Bot Pause` → `IF Bot Paused`; se `paused=true` o bot
  silencia e a conversa fica com a equipe.
- Frontend `barbearia-frontend/app/admin/crm/page.tsx`: botão "Assumir atendimento"
  / "Devolver ao bot" em cada card do Kanban (visível apenas para leads com cliente
  vinculado). Commit `4d43144` no repo do frontend.

**Deploy realizado:**
- Backend reconstruído (`docker compose up --build backend`).
- Workflow n8n atualizado via API REST (`versionId 7966507f`).
- Endpoint testado: `GET /bot/clients/paused-status` retorna `{"paused":false,...}`.

---

## ✅ Sessão 2026-06-23 — parte 2: funil CRM + serviço Corte+Barba

### Problema 1 — "Corte e Barba" não entrava no sistema

**Causa raiz:** a tool `criar_agendamento` aceita um único `service_id`. Sem serviço
combo no banco, a IA entrava em loop (4+ chamadas repetidas a `verificar_disponibilidade`)
e não criava nenhum agendamento.

**Correção:**
- Serviço `"Corte + Barba"` inserido direto no banco de produção: `id=15`, categoria
  `combo`, 75 min, R$140. Vinculado a Taylor, Thedy e Pablo via `barber_services`.
- System prompt da Raquel atualizado no n8n via API REST: ela agora sabe que o combo
  existe e **não deve criar dois agendamentos separados**.
- Workflow reativado (`versionId: fe68c6dd`).
- `scripts/seed.py` atualizado com o serviço e os vínculos (para futuros reseeds).

### Problema 2 — Funil CRM não alimentado pelo WhatsApp

**Causa raiz:** o bot nunca tocava nas tabelas `leads`/`lead_events` — o CRM era
100% manual.

**Correção em `app/api/bot.py` (commit `ea97257`):**
- `upsert_client`: quando um **novo cliente** chega pelo WhatsApp, cria `Lead` em
  estágio `novo_contato` com `source=whatsapp`.
- `create_appointment`: quando o bot confirma um horário, avança o lead do cliente
  para `agendado` (se ainda estiver em `novo_contato` ou `conversando`).
- Histórico registrado em `lead_events` a cada transição.
- Clientes já cadastrados que retornam não geram novo lead.

### Deploy realizado
- `bot.py` copiado para a VM via SCP + `docker compose restart backend`.
- Commit `ea97257` pushado para `origin/main`.
- `workflows.json` local atualizado com o novo prompt (referência; versão ativa
  está no n8n da VM).

> ⚠️ **git pull na VM ainda quebra** por `dubious ownership`
> (`/opt/barbeariapro` pertence a `root`, SSH entra como outro user).
> Workaround atual: copiar arquivos via `/tmp` + `sudo cp`. Para corrigir de vez:
> `sudo git config --global --add safe.directory /opt/barbeariapro` na VM.

---

## Pendências imediatas (próxima sessão)

- [ ] **Corrigir `git pull` na VM** — rodar `sudo git config --global --add safe.directory /opt/barbeariapro` para poder fazer pull normalmente.
- [ ] **HTTPS + domínio** — env ativo usa IP `34.95.199.134`. Commit `876d841`
  trocou para `taylorethedy.app` / `api.taylorethedy.com` no código, mas não foi
  aplicado ao `.env`/Nginx da VM. `deploy/nginx.conf` + certbot prontos.
- [ ] **Fechar portas** ao mundo após HTTPS (5678/8000/3000/8080 hoje abertas).
- [ ] **Backup automatizado** dos volumes Docker da VM (zeramento mostrou que não há).
- [ ] **Validar lembrete 24h** end-to-end (`CronReminder24h01` ativo, mas nunca testado com agendamento real).

---

## Estado da Fase 2 — Google Calendar (MERGEADA em `main`)

OAuth + worker de sync `appointments → Google Calendar`, isolado do bot.
Entregas (commits `a973514`, `447cbb0`, `10be0ca`, `1773b30`):
- Config + cripto Fernet de token (`app/core/config.py`, `app/core/crypto.py`)
- Cliente Google Calendar (`app/services/google_calendar.py`)
- Router OAuth `/integracoes/google/calendar/*` (`app/api/integracoes.py`)
- Worker `push_appointment` via BackgroundTask (`app/services/calendar_sync.py`),
  hooks em `app/api/agenda.py` e `app/api/barbeiro.py`
- Página `/admin/configuracoes` + agenda barbeiro mobile-first (frontend)
- ~30 testes de Calendar/OAuth/worker

> ⚠️ A conexão Google Calendar precisa ser refeita na produção restaurada
> (tokens OAuth estavam no banco antigo, que foi perdido). Reconectar via
> `/admin/configuracoes` → "Conectar Google Calendar".

---

## Próximas features por ROI (pós-deploy estável)

| # | Feature | Esforço | Observação |
|---|---|---|---|
| 1 | Lembrete 24h via WhatsApp | Baixo | `CronReminder24h01` ativo; validar end-to-end com agendamento real |
| 2 | Cron de reativação | Trivial | `CronReactivation1` já ativo; `POST /internal/loyalty/reactivation/run` existe |
| 3 | HTTPS + domínio | Médio | Pré-requisito para vender; scripts prontos em `deploy/` |
| 4 | Export CSV comissões/faturamento | Baixo | Queries já no dashboard |

### Fase 3 (BLOQUEADA — não iniciar sem aprovação)
Régua de follow-up 20min/24h/48h, objeções no prompt n8n, status CRM via Calendar.
Trava de segurança: `app/services/whatsapp.py:17` (dry-run nativo).

---

## Containers em produção (VM, 2026-06-23)

```
barbeariapro-app-backend    :8000   (healthy)
barbeariapro-app-frontend   :3000   (healthy)
barbeariapro-postgres       :5432   (healthy)
evolution_api               :8080
evolution_postgres          (interno)
evolution_redis             (interno)
n8n                         :5678
```
