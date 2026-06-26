# CURRENT_SPRINT.md
> Estado do desenvolvimento em **2026-06-26**. Atualizar a cada sessão.
> Companheiros: `PROJECT_CONTEXT.md` (estado/infra), `DECISIONS.md` (D-01..D-41), `CLAUDE.md` (memória técnica).

---

## Branch ativo

- **Backend repo** (`main`): commit **`2dd94f1`** (+ `DECISIONS.md` com D-40/D-41 **não commitado**).
- **Backend na VM**: commit **`3e138b5`** — **atrás do repo**; deploy da Fase 1.1 **pendente**.
- **Frontend** (`main`): commit `f5397a8` — local. Deploy na VM via scp+build (repo remoto não existe).

---

## 🔴 BLOQUEIO Nº 1 — Bot WhatsApp NÃO ENTREGA respostas (número restrito)

**Status:** recebe ✅ / **não envia ❌**. Causa raiz **confirmada** (D-41): número `5563920001734`
**restrito pelo WhatsApp**. Descartado todo o software (OpenAI/CRM/n8n/webhook/sessão/**versão Evolution
até 2.4.0-rc2 com LID**). Falha global (2 números testados, `status: ERROR`).

**PRÓXIMO PASSO (decisão tomada):** **migrar para WhatsApp Cloud API oficial (Meta)** com **número novo dedicado**.
- Pré-requisitos do usuário: Meta Business verificado + número limpo dedicado + templates aprovados (lembrete/reativação).
- Trabalho nosso: reescrever `app/services/whatsapp.py` (Graph API `POST /{phone_id}/messages`); novo parser
  de webhook (formato Meta + verificação `X-Hub-Signature-256` + handshake `hub.challenge`); repontar envio
  no n8n; templates; mídia. Manter Evolution como fallback até validar.
- **NÃO** insistir em Evolution/Baileys nem em upgrade de versão (já testado e descartado).
- Diagnóstico rápido p/ revalidar: `POST /message/sendText/Barbearia` direto na Evolution (via SSH) → se
  `status: ERROR` global, segue restrito.

## 🟢 Sessão 2026-06-26 — Auditoria arquitetural + Segurança (Fase 1) + incidente WhatsApp

- **Auditoria completa** do projeto + **`CLAUDE.md`** criado (memória técnica viva) — commit `15692b4`.
- **Fase 1.1 segurança** (commit `13822a1`): `secrets_match()` (tempo-constante) em `security.py`, usado em
  `deps.py`/`wa_webhook.py`; `print` debug → `_logger.debug`. **Falta deploy na VM.**
- **Firewall** (D-40): 5678/8080 fechadas (n8n/Evolution só por SSH tunnel). **`SECRET_KEY` prod: forte** (não rotacionar).
- **Chave OpenAI rotacionada e antiga revogada** (vazara em `credentials.json` no histórico git).
- **Incidente WhatsApp** (D-41): upgrade Evolution 2.4.0-rc2 testado e **revertido p/ 2.3.7** (digest pinada na VM).

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

## Pendências prioritárias (2026-06-26)

- [ ] **[CRÍTICO] Migrar WhatsApp p/ Cloud API** (D-41) — bot não entrega; número restrito. Ver BLOQUEIO Nº 1.
- [ ] **Deploy da Fase 1.1 na VM** — repo `main` (`2dd94f1`) à frente; VM em `3e138b5` (ainda com `print`).
      `git pull` + rebuild backend (ver PROJECT_CONTEXT §2).
- [ ] **Commitar `DECISIONS.md`** (D-40/D-41 estão no working tree, não commitados).
- [ ] **Fase 1.3 — limpar histórico git** de `credentials.json` (`git filter-repo` + force-push). Seguro
      agora (chave já revogada).
- [ ] **HTTPS + domínio** — nginx pronto; falta registrar domínio + certbot. Depois mover 8000/3000 p/ trás do nginx.
- [ ] **Reconciliar `docker-compose.yml`** repo vs VM (VM fixou Evolution na digest 2.3.7; repo tem `:latest`).
- [ ] **Backup automatizado** dos volumes/DB Docker · **auto-restart da VM** (WhatsApp cai quando a VM reinicia).
- [ ] **Frontend git remoto** — remote morto (`DoctorDCombo/...`); mover p/ repo vivo (risco de perda de histórico).
- [ ] **`workflows.json` local diverge da VM** — exportar da VM antes de editar.

> Frentes de produto saudáveis para avançar em paralelo (ver `CLAUDE.md` §8): Frontend F3 (quebrar
> monólitos CRM 1389/Agenda 720), Caixa, Pacotes/Assinaturas, Dashboard executivo.

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
