# CURRENT_SPRINT.md
> Estado do desenvolvimento em **2026-06-25**. Atualizar a cada sessão.

---

## Branch ativo

- **Backend** (`main`): commit `3e138b5` — local e VM em sync.
- **Frontend** (`main`): commit `f5397a8` — local. Deploy na VM via scp+build (repo remoto não existe).

---

## 🔴 TAREFA EM ABERTO — Bot responses no CRM Inbox

**Status:** Mensagens de **cliente** aparecem no Inbox ✅. Mensagens do **bot** NÃO confirmadas ❌.

**PRÓXIMO PASSO OBRIGATÓRIO (primeiro ato da próxima sessão de backend):**
```bash
# 1. Enviar mensagem WhatsApp de teste para o número da barbearia
# 2. Aguardar resposta do bot
# 3. Ler logs do backend:
gcloud compute ssh barbeariapro --project=barberiapro-app --zone=southamerica-east1-a --command=\
  "docker logs barbeariapro-app-backend --since=5m 2>&1 | grep -v health"
```
O log mostrará `[WA_WEBHOOK] event=...` para todos os eventos recebidos.
Após confirmar que `send.message` é recebido e bot messages aparecem no DB:
- Substituir `print` por `_logger.debug` em `wa_webhook.py`
- Marcar como ✅ aqui

---

## ✅ Sessão 2026-06-25 (2ª) — Auditoria bot + WhatsApp + integracoes

### Contexto
VM estava TERMINATED desde ~24/06 — bot offline, cron parado. Sessão focada em diagnóstico e correção.

### Diagnóstico realizado
| Item | Achado |
|---|---|
| Barbeiros no DB | 5 ativos: Taylor, Thedy, Marciana, Sandra, Pablo |
| System prompt bot | Só listava Taylor e Thedy — causa do bug "Marciana não trabalha aqui" |
| CronReminder24h01 | Saudável — 5 execuções em 24/06; parou porque VM desligou |
| Evolution | Instância `close` após restart da VM |
| n8n login | `admin@barbearia.com` email correto; senha falhou — resetada |

### Correções aplicadas

**1. System prompt n8n (AI Agent):**
- Seção `OS BARBEIROS` atualizada para incluir todos os 5 barbeiros
- versionId: `8ae50a30-49ac-4cd1-b290-e7e68bd89c25`
- Atualizado via `PATCH /rest/workflows/25QZQ664N6hrIg59` (não PUT)

**2. WhatsApp reconectado:**
- Instância Evolution deletada e recriada (sessão antiga inválida)
- instanceId: `6c3d8682-7d76-49cb-b0b4-e05893764c78`
- QR escaneado — estado: `open`
- ⚠️ Webhook foi erroneamente apontado para n8n na recriação → corrigido para FastAPI:
  `http://host.docker.internal:8000/bot/wa-webhook`

**3. n8n senha resetada:**
- Login estava falhando com todas as variantes testadas
- Senha redefinida para `Barbearia2026` via bcrypt no SQLite (só tabela `user`)
- Campo correto para login: `emailOrLdapLoginId` (não `email`)

**4. Feature: `/admin/integracoes` funcional:**
- Commit backend: `3e138b5` — `GET /integracoes/whatsapp/status` + `GET /integracoes/whatsapp/qr`
- Commit frontend: `f5397a8` — card WhatsApp com status + modal QR auto-refresh 30s
- Deploy na VM: scp + `docker compose -f docker-compose.app.yml up -d --build frontend`
- Acesso: `http://34.95.199.134:3000/admin/integracoes`

---

## ✅ Sessão 2026-06-25 (1ª) — Frontend shell + nginx

**Commit:** `f5397a8` no frontend (inclui 1ª + 2ª sessão do dia — apenas local, sem remote funcional)

**Componentes criados em `components/layout/`:**
- `AdminSidebar.tsx`, `AdminHeader.tsx`, `AdminShell.tsx`

**Build:** TypeScript clean, ESLint 0 erros/warnings, `next build` 15 rotas OK.

**nginx:** porta 80 → localhost:3000. `http://34.95.199.134` funciona. SSL pendente.

---

## ✅ Sessão 2026-06-24 (2ª) — Webhook direto + correções CRM

- `app/api/wa_webhook.py` — webhook direto Evolution→FastAPI (sem delay do n8n)
- Migration `0011_grant_crm_tables` — GRANT CRUD ao `barber_app`
- Evolution webhook reconfigurado: `http://host.docker.internal:8000/bot/wa-webhook`
- n8n: `Log Outbound Message` em série após `Send Response`; `Log Inbound` desabilitado

---

## ✅ Sessão 2026-06-24 (1ª) — CRM Conversacional Fases 2–5

- Migration `0010_conversations`: tabelas `conversations`/`messages`/`attachments`
- `app/services/conversation.py`, `app/services/sse_broker.py`
- Router `app/api/conversations.py` (scroll infinito, busca GIN)
- Frontend: toggle Kanban⇄Inbox, `ConvListItem`, `MsgBubble`, `ConvMessagePanel`, `InboxView`
- `GET /crm/stream?token=<jwt>` — SSE em tempo real

---

## ✅ Sessões 2026-06-23

- Restauração da VM do zero; bot WhatsApp end-to-end funcionando
- Funil CRM, pausa do bot, `POST /bot/messages`
- n8n: nós Log em série (D-18 aplicado)

---

## Pendências prioritárias

- [ ] **[CRÍTICO] Confirmar bot responses no Inbox** — debug print ativo; ver "TAREFA EM ABERTO" acima
- [ ] **Remover debug logging** (`print [WA_WEBHOOK]`) após confirmar evento Evolution
- [ ] **HTTPS + domínio** — nginx configurado; falta registrar `taylorethedy.app` e rodar certbot
- [ ] **Fechar portas** ao mundo após HTTPS (5678/8000/3000/8080 abertas)
- [ ] **Backup automatizado** dos volumes Docker (VM já foi zerada uma vez; ficou TERMINATED em 2026-06-25)
- [ ] **Configurar auto-restart** da VM ou alerta quando VM cair (WhatsApp cai junto)
- [ ] **`workflows.json` local diverge da VM** — exportar da VM antes de qualquer edição local
- [ ] **Frontend git remoto** — `DoctorDCombo/barbearia-frontend` não existe; considerar mover para `augustopegoraro-droid/barbeariapro` ou criar novo repo

---

## Próximas features por ROI (pós-estabilização)

| # | Feature | Esforço | Observação |
|---|---|---|---|
| 1 | Confirmar bot responses no Inbox | Baixo | Debug já ativo; só precisa testar |
| 2 | HTTPS + domínio | Médio | nginx pronto; falta registrar domínio (~$20/ano) |
| 3 | Lembrete 24h via WhatsApp | Baixo | `CronReminder24h01` ativo e saudável |
| 4 | Cron de reativação | Trivial | `CronReactivation1` ativo |
| 5 | Export CSV comissões | Baixo | Queries já no dashboard |
| 6 | VM sempre ligada | Baixo | Verificar política de preemption / startup script |
