# CURRENT_SPRINT.md
> Estado do desenvolvimento em **2026-06-24**. Atualizar a cada sessão.

---

## Branch ativo

`main` — local e VM em **`f72cd59`** (em sync total).

---

## ✅ Sessão 2026-06-24 — CRM Conversacional Fases 2–5

### Objetivo
Evoluir o CRM de polling de `message_log` para um inbox em tempo real com histórico
estruturado, persistência de todos os tipos de mensagem e atualização via SSE.

### Fase 2 — Persistência unificada de conversa (commit `f87f579`)

**Migration `0010_conversations`** (aplicada na VM como superuser postgres):
- Tabelas: `conversations`, `messages`, `attachments`
- ENUMs: `conversation_status`, `message_sender_type`, `message_type`, `attachment_media_type`
- Índice GIN pg_trgm em `messages.body_text`
- Índice parcial de idempotência `(conversation_id, wa_message_id, sender_type) WHERE wa_message_id IS NOT NULL`
- Backfill de `message_log.body_text` → `messages` (ON CONFLICT DO NOTHING)
- RLS aplicado nas 3 tabelas

**Novos arquivos:**
- `alembic/versions/0010_conversations.py`
- `models/conversation.py` — `Conversation`, `Message`, `Attachment` (SQLAlchemy 2.0)
- `app/services/conversation.py` — porta única de escrita (`get_or_create_conversation`, `record_message`)
- `app/services/sse_broker.py` — broker SSE em memória (asyncio Queues por org)

**Arquivos modificados:**
- `models/enums.py` — 4 novos ENUMs
- `models/__init__.py` — exports dos novos models
- `app/api/bot.py:log_message` — delegado para `conversation_service`; grava sem cliente (1º contato)
- `app/api/crm.py:get_lead_messages` — repontado de `message_log` para `messages`
- `app/services/reminders.py` e `reactivation.py` — chamam `record_message(sender_type=system)`
- `app/main.py` — include_router conversations

**Invariantes mantidas:**
- `message_log` intocado — continua para reminders/reativação com template/retry
- Avanço de estágio do funil em bot.py não foi alterado
- `get_bot_db` e `get_tenant_db` não foram tocados

### Fase 3 — APIs de leitura (commit `7ee6cbf`)

Novo router em `app/api/conversations.py` (prefixo `/crm`):
- `GET /crm/conversations` — lista paginada por cursor `base64({ts,id})`
- `GET /crm/conversations/search?q=` — ILIKE com índice GIN
- `GET /crm/conversations/{id}` — detalhe
- `GET /crm/conversations/{id}/messages` — scroll por `?before=<id>`
- `PATCH /crm/conversations/{id}/read` — zera unread_count

**Fix de SyntaxError:** parâmetros com `Depends(...)` (sem default) devem vir antes de
parâmetros com default no FastAPI — parâmetro `q: str = Query(...)` reordenado.

### Fase 4 — UI Inbox 3 painéis (commit `effdd77` + deploy via SCP)

Adições em `barbearia-frontend/app/admin/crm/page.tsx`:
- Toggle **Kanban ⇄ Inbox** no header da página
- Novos componentes: `ConvListItem`, `MsgBubble`, `ConvMessagePanel`, `InboxView`
- `MsgBubble`: cores por sender_type; áudio (transcript), imagem, documento
- `ConvMessagePanel`: scroll infinito, poll 10 s, `PATCH /read` ao abrir
- `InboxView`: lista com cursor pagination, poll 15 s, layout responsivo

Novos tipos em `barbearia-frontend/types/index.ts`:
`MessageAttachment`, `ConversationMsg`, `MessagePageData`, `ConversationItem`, `ConversationListData`

### Fase 5 — SSE em tempo real (commits `effdd77` + `f72cd59`)

**Backend:**
- `GET /crm/stream?token=<jwt>` em `app/api/conversations.py:387`
- Token via query param (browser `EventSource` não suporta headers)
- Valida JWT → `org_id` → subscreve fila no `sse_broker`
- Envia `{"type":"connected"}` imediatamente; keepalive `: keepalive\n\n` a cada 25 s
- Desregistra do broker no `finally` (disconnect seguro)
- `headers: Cache-Control: no-cache, X-Accel-Buffering: no`
- `_publish` em `conversation.py` chamado após `flush()` (msg.id garantido), antes do `commit()`

**Frontend (InboxView):**
- Abre `EventSource` no `useEffect` do mount; fecha no cleanup
- Evento `new_message` → atualiza preview/unread na lista; propaga `sseMsg` para painel ativo via `selectedRef`
- `setSseMsg(null)` ao trocar de conversa (evita append em conversa errada)

**Frontend (ConvMessagePanel):**
- Aceita `sseMsg?: ConversationMsg | null` via prop
- `useEffect` em `sseMsg` → append com deduplicação por `id`
- Polling 10 s permanece como fallback

### Deploy desta sessão

| Etapa | Comando | Resultado |
|---|---|---|
| Commits backend | `git add ... && git commit && git push` | 5 commits em main |
| Pull VM + rebuild backend | `sudo git -C /opt/barbeariapro pull && docker compose -f docker-compose.app.yml up -d --build backend` | ✅ healthy |
| SCP frontend | `gcloud compute scp ... && sudo cp ... && docker compose up -d --build frontend` | ✅ healthy |
| Migration 0010 | `docker exec -e DATABASE_URL=...postgres... python -m alembic upgrade head` | ✅ aplicada |

**Erro encontrado e corrigido:** `sse_broker.py` e `_publish` em `conversation.py` não foram
incluídos no commit da Fase 2 — commitados separadamente em `f72cd59`. Causa: arquivo novo
não rastreado (`git status` mostrava `??`) e modificação local não staged.

---

## ✅ Sessão 2026-06-23 — parte 5: sincronização WhatsApp↔CRM em tempo real

**Backend (commit `a11e0be`):**
- `0009_conversation_log`: `body_text TEXT` em `message_log`
- `POST /bot/messages`: grava inbound/outbound; idempotente por `whatsapp_message_id`;
  atualiza `last_contact_at`; move lead `novo_contato→conversando` no inbound
- `GET /crm/leads/{id}/messages`: histórico via `client_id` (via `message_log.body_text`)

**n8n (via API REST — não git):** 2 nós Log Inbound/Outbound em série (ver D-18).

---

## ✅ Sessão 2026-06-23 — parte 4: bot responde fora do horário

Bot atende 24/7 com prefixo `[FORA_DO_HORARIO]` fora do expediente.
Commit `7464def`, workflow n8n atualizado (versionId `7519aa44`).

---

## ✅ Sessão 2026-06-23 — parte 3: funil completo + pausa do bot via CRM

- `upsert_client`: clientes antigos sem lead ativo recebem novo lead em `novo_contato`
- `GET /bot/clients/paused-status`, `PATCH /clientes/{id}/bot-pause`
- Migration `0008_client_bot_paused` (formal — coluna já existia por ALTER TABLE)
- Frontend: botão "Assumir / Devolver bot" nos cards do Kanban
Commit `4721316`, workflow n8n atualizado (`versionId 7966507f`).

---

## ✅ Sessão 2026-06-23 — parte 2: funil CRM + serviço Corte+Barba

- Serviço `"Corte + Barba"` (id=15, 75min, R$140) inserido no banco
- `upsert_client`: novo cliente → Lead `novo_contato`; bot confirma agendamento → `agendado`
- Commit `ea97257`

---

## ✅ Sessão 2026-06-23 — parte 1: restauração da VM de produção

VM encontrada zerada. Stack inteira reconstruída do zero.
Bot WhatsApp funcionando end-to-end (conversa + agendamento).

---

## Pendências imediatas (próxima sessão)

- [ ] **[CRÍTICO] Confirmar SSE e Inbox ao vivo**: abrir `/admin/crm` → Inbox → mandar
  mensagem WhatsApp → verificar que preview atualiza em tempo real e mensagem aparece
  no painel sem reload. Primeira confirmação ao vivo do sistema completo.
- [ ] **Sincronizar `workflows.json`** — arquivo local tem conexões PARALELAS; VM tem SÉRIE.
  Exportar da VM antes de qualquer edição:
  ```bash
  gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a \
    --command="curl -s -b 'n8n-auth=<cookie>' http://localhost:5678/rest/workflows/25QZQ664N6hrIg59" \
    > workflows.json
  ```
- [ ] **HTTPS + domínio** — env ativo usa IP `34.95.199.134`. `deploy/nginx.conf` + certbot prontos.
- [ ] **Fechar portas** ao mundo após HTTPS (5678/8000/3000/8080 hoje abertas).
- [ ] **Backup automatizado** dos volumes Docker da VM (VM já foi zerada uma vez).
- [ ] **Validar lembrete 24h** end-to-end (`CronReminder24h01` ativo, nunca testado).

---

## Próximas features por ROI (pós-deploy estável)

| # | Feature | Esforço | Observação |
|---|---|---|---|
| 1 | Lembrete 24h via WhatsApp | Baixo | `CronReminder24h01` ativo; validar end-to-end |
| 2 | Cron de reativação | Trivial | `CronReactivation1` ativo; `POST /internal/loyalty/reactivation/run` existe |
| 3 | HTTPS + domínio | Médio | Pré-requisito para vender; scripts prontos em `deploy/` |
| 4 | Envio de mensagem pelo CRM (painel Inbox) | Médio | Evolution API disponível; falta endpoint + UI |
| 5 | Export CSV comissões/faturamento | Baixo | Queries já no dashboard |

### Fase 3 do roadmap original (BLOQUEADA — não iniciar sem aprovação)
Régua de follow-up 20min/24h/48h, objeções no prompt n8n, status CRM via Calendar.
Trava de segurança: `app/services/whatsapp.py:17` (dry-run nativo).
