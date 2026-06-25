# CURRENT_SPRINT.md
> Estado do desenvolvimento em **2026-06-25**. Atualizar a cada sessão.

---

## Branch ativo

- **Backend** (`main`): commit `dfdf7b9` — local e VM em sync.
- **Frontend** (`main`): commit `9310df0` — local. Deploy na VM via tar+SSH (repo remoto não existe).

---

## 🔴 TAREFA EM ABERTO — Bot responses no CRM Inbox

**Status:** Mensagens de **cliente** aparecem no Inbox ✅. Mensagens do **bot** NÃO confirmadas ❌.

**PRÓXIMO PASSO OBRIGATÓRIO (primeiro ato da próxima sessão de backend):**
```bash
# 1. Enviar mensagem WhatsApp de teste para o número da barbearia
# 2. Aguardar resposta do bot
# 3. Ler logs do backend:
ssh -i ~/.ssh/google_compute_engine apleandro@34.95.199.134 \
  "sudo docker logs barbeariapro-app-backend --since=5m 2>&1 | grep -v health"
```
O log mostrará `[WA_WEBHOOK] event=...` para todos os eventos.
Após confirmar o evento correto e bot messages no DB:
- Substituir `print` por `_logger.debug` em `wa_webhook.py`
- Marcar como ✅ aqui

---

## ✅ Sessão 2026-06-25 — Frontend shell + nginx

### Admin shell (FASE 4 — implementação completa)
**Commit:** `9310df0` no frontend (apenas local — sem remote funcional)

**Componentes criados em `components/layout/`:**
- `AdminSidebar.tsx` — colapsável (240px↔64px, 220ms cubic-bezier), persistência `localStorage sb_nav_v1_collapsed`, mobile overlay com backdrop, badges estáticos (Agenda:2, Conversas:5), grupos OPERACIONAL/GESTÃO/MARKETING/CONFIGURAÇÕES
- `AdminHeader.tsx` — breadcrumb dinâmico por `ROUTE_META` (14 rotas mapeadas), bell com dot amber, hamburger mobile
- `AdminShell.tsx` — compõe sidebar + header, controla `mobileOpen`

**Arquivos modificados/criados:**
- `app/admin/layout.tsx` — usa `AdminShell`
- `app/barbeiro/layout.tsx` — passthrough
- `app/globals.css` — tokens dark theme (`--background: #0a0a0a`, `--primary: #f59e0b`, etc.) + `@keyframes slideDown/fadeIn`
- `app/layout.tsx` — Inter font, `SessionProvider`, `TooltipProvider`, `class="dark"` no `<html>`
- `package.json` — shadcn/ui v4.11.0, Tailwind v4, Lucide React, clsx, tailwind-merge
- `components.json` — config shadcn
- `lib/utils.ts` — `cn()` helper

**Componentes shadcn/ui instalados:** `button`, `card`, `dialog`, `input`, `select`, `tooltip`, `badge`

**6 rotas novas do admin:**
- `/admin/conversas` — redirect server-side → `/admin/crm?view=inbox`
- `/admin/fidelidade`, `/admin/campanhas`, `/admin/empresa`, `/admin/usuarios`, `/admin/integracoes` — placeholders "Em breve"

**CRM page (`app/admin/crm/page.tsx`) — correções:**
- View inicializada via `window.location.search` (não `useSearchParams` — evita Suspense)
- Bugs de mutação de variável durante `.map()` corrigidos (`lastDate`, `lastDateLabel` → índice)
- Import não-utilizado `ConversationListData` removido
- ESLint: 25 problemas → 0 (eslint-disable pontuais para padrões legítimos)

**Build:** TypeScript clean, ESLint 0 erros/warnings, `next build` 15 rotas OK.

### Deploy frontend
Procedimento tar+SSH (ver PROJECT_CONTEXT §2):
```bash
tar -czf - --exclude='.git' --exclude='node_modules' --exclude='.next' \
  --exclude='projetopagina.html' \
  -C /Users/apleandro/dev/barbeariapro/barbearia-frontend . | \
  ssh -i ~/.ssh/google_compute_engine apleandro@34.95.199.134 \
  "sudo tar -xzf - -C /opt/barbeariapro/barbearia-frontend/ && echo 'sync ok'"
```
Depois: `sudo docker compose -f docker-compose.app.yml up -d --build frontend`

### nginx instalado na VM
- `apt install nginx certbot python3-certbot-nginx`
- Config: `/etc/nginx/sites-available/barbeariapro` (`default_server` porta 80 → `localhost:3000`)
- `systemctl enable nginx` — inicia no boot
- **`http://34.95.199.134` agora funciona** (porta 80 via nginx)
- SSL pendente: domínio `taylorethedy.app` não registrado

---

## ✅ Sessão 2026-06-24 (2ª) — Webhook direto + correções CRM

- `app/api/wa_webhook.py` — webhook direto Evolution→FastAPI (sem delay do n8n)
- Migration `0011_grant_crm_tables` — GRANT CRUD ao `barber_app`
- Evolution webhook reconfigurado: `http://host.docker.internal:8000/bot/wa-webhook`
- n8n: `Log Outbound Message` em série após `Send Response`; `Log Inbound` desabilitado
- Acidente `user-management:reset` → novas credenciais n8n: `admin@barbearia.com` / `Barbearia@2026!`

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
- [ ] **Backup automatizado** dos volumes Docker (VM já foi zerada uma vez)
- [ ] **Validar lembrete 24h** end-to-end (`CronReminder24h01` ativo, nunca testado)
- [ ] **`workflows.json` local diverge da VM** — exportar da VM antes de qualquer edição local
- [ ] **Frontend git remoto** — `DoctorDCombo/barbearia-frontend` não existe; considerar mover para `augustopegoraro-droid/barbeariapro` ou criar novo repo

---

## Próximas features por ROI (pós-estabilização)

| # | Feature | Esforço | Observação |
|---|---|---|---|
| 1 | Confirmar bot responses no Inbox | Baixo | Debug já ativo; só precisa testar |
| 2 | HTTPS + domínio | Médio | nginx pronto; falta registrar domínio (~$20/ano) |
| 3 | Lembrete 24h via WhatsApp | Baixo | `CronReminder24h01` ativo; validar end-to-end |
| 4 | Cron de reativação | Trivial | `CronReactivation1` ativo |
| 5 | Export CSV comissões | Baixo | Queries já no dashboard |
