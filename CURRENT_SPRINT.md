# CURRENT_SPRINT.md
> Estado do desenvolvimento em **2026-06-24**. Atualizar a cada sessão.

---

## Branch ativo

`main` — local e VM em **`dfdf7b9`** (em sync total).

---

## 🔴 TAREFA EM ABERTO — Bot responses no CRM Inbox

**Status:** Mensagens de **cliente** aparecem no Inbox ✅. Mensagens do **bot** NÃO aparecem ❌.

### O que foi feito nesta sessão
1. Webhook direto `POST /bot/wa-webhook` criado — cliente gravado imediatamente sem delay
2. Migration `0011` aplicada — GRANT de CRUD ao `barber_app` nas tabelas CRM
3. Evolution webhook reconfigurado para apontar a FastAPI (não mais n8n)
4. n8n workflow corrigido: `Log Outbound Message` em série após `Send Response`
5. Evento `SEND_MESSAGE` adicionado ao webhook da Evolution
6. Código em `wa_webhook.py` trata `send.message` como `sender_type=bot`

### Causa raiz identificada mas não confirmada
Evolution API v2.3.7 pode não disparar `MESSAGES_UPSERT` com `fromMe=true` para msgs
enviadas via API. Adicionamos `SEND_MESSAGE` como evento alternativo. Debug print ativo.

### PRÓXIMO PASSO OBRIGATÓRIO (deve ser o PRIMEIRO ato da próxima sessão)
```bash
# 1. Enviar mensagem WhatsApp de teste
# 2. Aguardar resposta do bot no WhatsApp
# 3. Ler logs do backend na VM:
gcloud compute ssh apleandro@barbeariapro --zone=southamerica-east1-a \
  --command="docker logs barbeariapro-app-backend --since=5m 2>&1 | grep -v health"
```
O log mostrará `[WA_WEBHOOK] event=...` para TODOS os eventos recebidos.
Com base no event name, ajustar o código se necessário.

Após confirmar o evento correto e bot messages no DB:
- Remover os commits de debug (`b8a793c`, `dfdf7b9`) ou substituir `print` por `_logger.debug`
- Atualizar esta seção como ✅

### Estado do DB (verificado 17:33 local)
```sql
-- Últimas mensagens em produção (org_id=1)
-- id=15..19 são todas client ou human (nenhuma bot do fluxo real)
-- id=11: única mensagem bot = teste manual em conv_id=10 (telefone errado)
-- conv_id=1 é a conversa real do Augusto (+556399368196, 8 dígitos)
```

---

## ✅ Sessão 2026-06-24 (2ª) — Webhook direto + correções CRM

### Webhook direto Evolution → FastAPI (`app/api/wa_webhook.py`)
**Novo arquivo:** `app/api/wa_webhook.py`
- `POST /bot/wa-webhook` — recebe eventos Evolution sem o delay de 5 s do n8n
- Grava `messages.upsert` inbound como `sender_type=client` imediatamente → SSE
- Encaminha payload ao n8n em background com retry 3× (bot IA continua funcionando)
- `send.message` → `sender_type=bot`; NÃO encaminha ao n8n (evita loop)
- Novas settings: `n8n_webhook_url`, `wa_webhook_secret` (em `app/core/config.py`)
- Registrado em `app/main.py`

### Migration 0011 (`alembic/versions/0011_grant_crm_tables.py`)
```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON conversations, messages, attachments TO barber_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app;
```
Aplicada manualmente antes do commit; `alembic_version` estampado para `0011` diretamente.

### Reconfiguração Evolution webhook
```
ANTES: Evolution → http://host.docker.internal:5678/webhook/whatsapp (n8n)
DEPOIS: Evolution → http://host.docker.internal:8000/bot/wa-webhook (FastAPI)
Eventos: MESSAGES_UPSERT, SEND_MESSAGE, CONNECTION_UPDATE, QRCODE_UPDATED
```
Feito via `POST /webhook/set/Barbearia` com body `{"webhook": {...}}` (não PUT).

### n8n workflow (id `25QZQ664N6hrIg59`, versionId `3473de06`, atualizado 16:26)
- `Log Inbound Message`: **DESABILITADO** (cliente já gravado pelo webhook direto; evita duplicata)
- `HTTP Flush Buffer → Code Horário Comercial` diretamente (antes passava por Log Inbound)
- `Send Response → Log Outbound Message`: em série ✅
- `Log Outbound Message` jsonBody: `$json["key"]["remoteJid"]` e `$json["message"]["conversation"]`
  (usa resposta da Evolution, não referências a nós anteriores que quebravam via SSH)
- **Descoberta crítica:** execuções 80/81 (14:09 e 14:22) usaram snapshot do workflow
  **sem** `Log Outbound Message` — o nó foi adicionado depois mas o n8n manteve o mesmo versionId.
  Futuras execuções usam o workflow atual com o nó.

### Acidente n8n `user-management:reset` (ver D-28)
Ao tentar debugar, o comando `docker exec n8n n8n user-management:reset` foi executado
acidentalmente. Conta de owner apagada. Recuperação via:
```bash
curl -X POST http://localhost:5678/rest/owner/setup \
  -H 'Content-Type: application/json' \
  -d '{"firstName":"Admin","lastName":"Admin","email":"admin@barbearia.com","password":"Barbearia@2026!"}'
```
**Novas credenciais n8n:** `admin@barbearia.com` / `Barbearia@2026!`

---

## ✅ Sessão 2026-06-24 (1ª) — CRM Conversacional Fases 2–5

### Fase 2 — Persistência unificada (commit `f87f579` → `f72cd59`)
- Migration `0010_conversations`: tabelas `conversations`/`messages`/`attachments` + RLS
- `models/conversation.py`, `app/services/conversation.py`, `app/services/sse_broker.py`
- `bot.py:log_message` delegado para `conversation_service`; grava sem cliente (1º contato)

### Fase 3 — APIs de leitura (commit `7ee6cbf`)
- Router `app/api/conversations.py` (prefixo `/crm`): list, search, detail, messages, read
- Scroll infinito por cursor `?before=<id>`; busca GIN pg_trgm

### Fase 4 — UI Inbox 3 painéis (commit `f046b9f` + SCP frontend)
- Toggle Kanban ⇄ Inbox no `/admin/crm`
- `ConvListItem`, `MsgBubble`, `ConvMessagePanel`, `InboxView`
- `POST /crm/conversations/{id}/send` — envio de mensagem pelo Inbox ✅ (confirmado funcionando)

### Fase 5 — SSE em tempo real (commits `effdd77` + `929c13e` + `f72cd59`)
- `GET /crm/stream?token=<jwt>` — SSE com keepalive 25 s
- `_publish` após `flush()` (msg.id garantido, antes do commit)
- Frontend: `EventSource` no mount, evento `new_message` atualiza preview/unread

---

## ✅ Sessões 2026-06-23 (partes 1–5)

- Restauração da VM do zero; bot WhatsApp end-to-end funcionando
- Funil CRM: `novo_contato → conversando → agendado`
- Pausa do bot via CRM (`GET /bot/clients/paused-status`, botão "Assumir")
- `POST /bot/messages` (log_message) implementado
- n8n: nós Log em série (D-18 aplicado)

---

## Pendências prioritárias

- [ ] **[CRÍTICO] Confirmar bot responses no Inbox** — ver seção "TAREFA EM ABERTO" acima
- [ ] **Remover debug logging** (`print [WA_WEBHOOK]`) após confirmar evento Evolution
- [ ] **HTTPS + domínio** — scripts em `deploy/nginx.conf` + certbot prontos
- [ ] **Fechar portas** ao mundo após HTTPS (5678/8000/3000/8080 abertas)
- [ ] **Backup automatizado** dos volumes Docker (VM já foi zerada uma vez)
- [ ] **Validar lembrete 24h** end-to-end (`CronReminder24h01` ativo, nunca testado)
- [ ] **`workflows.json` local diverge da VM** — exportar da VM antes de qualquer edição local

---

## Próximas features por ROI (pós-estabilização)

| # | Feature | Esforço | Observação |
|---|---|---|---|
| 1 | Lembrete 24h via WhatsApp | Baixo | `CronReminder24h01` ativo; validar end-to-end |
| 2 | HTTPS + domínio | Médio | Pré-requisito para vender |
| 3 | Cron de reativação | Trivial | `CronReactivation1` ativo |
| 4 | Export CSV comissões | Baixo | Queries já no dashboard |
