# CURRENT_SPRINT.md
> Estado do desenvolvimento em **2026-06-26**. Atualizar a cada sessão.
> Companheiros: `PROJECT_CONTEXT.md` (estado/infra), `DECISIONS.md` (D-01..D-43), `CLAUDE.md` (memória técnica), `barbearia-frontend/AGENTS.md` (frontend).

---

## Branch ativo

- **Backend repo** (`main`): commit **`469f784`** — inclui o **PR #2** (reagendar aceita `barber_id`, D-43).
- **Backend na VM**: commit **`469f784`** — **deployado 2026-06-26 16:43** (reagendar + Fase 1.1 + CLAUDE.md). Atrás do repo só pelo commit de docs.
- **Frontend:** branch **`feat/design-system-react-query-f1-f3`** (`3399587`) = **toda a F1–F3**.
  **NÃO mergeado em `main`** (frontend `main` = `f5397a8`), **NÃO deployado**. Remote morto.
  ➜ Continuar: `cd barbearia-frontend && git checkout feat/design-system-react-query-f1-f3`.

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

## 🟢 Sessão 2026-06-26 (4ª) — Mensalidade/Assinatura do cliente final (D-44)

> Feature nova, full-stack, **só no staging** — não mergeada/deployada. Detalhes em **D-44**.
> Plano: `/Users/apleandro/.claude/plans/glimmering-greeting-gem.md`.

- **Modelagem:** `models/membership.py` (4 tabelas + enum `MembershipStatus`); migrations `0012_memberships`
  (tabelas + RLS) e `0013_grant_membership_tables` (GRANT ao `barber_app`). Aplicadas no staging com
  `ADMIN_DATABASE_URL` (o app `barber_app` não tem DDL). **Produção pendente.**
- **Regra de negócio:** `app/services/membership.py` (venda, consumo com baixa atômica anti-double-spend,
  rateio de receita, reversão idempotente, expiração). Combo fixo; receita rateada no uso (deferred);
  `appointments` **não** alterada (vínculo via `membership_usages.appointment_id UNIQUE`).
- **API:** `app/api/memberships.py` (CRUD de planos [manager], venda/consumo/cancelar/renovar/leitura
  [admin], `/internal/memberships/expirar` [cron]). Integração mínima em `app/api/barbeiro.py` (concluir
  por mensalidade não cria Payment; cancelar/faltou estorna o saldo).
- **Frontend:** `/admin/assinaturas` (abas Planos|Assinaturas) + `hooks/use-assinaturas.ts` +
  `components/assinaturas/*` (plano CRUD com combo, `MembershipCard` com avisos de vencimento/último pacote,
  histórico de uso, venda) + item de sidebar "Assinaturas". `tsc`/`eslint`/`build` limpos.
- **Testes:** `tests/test_membership_unit.py` (10) + `tests/test_membership_integration.py` (5). Suíte
  backend **226 pass / 3 fail ambientais / 1 skip**.
- **Pendente:** mergear/deployar; rodar migrations 0012/0013 em produção; validação no browser; consumo do
  pacote pela tela da Agenda (toggle "usar mensalidade", opcional) e linha "Mensalidade" no financeiro (E8).

---

## 🟢 Sessão 2026-06-26 (3ª) — Rearquitetura de Frontend (F1–F3) + backend reagendar

> Frontend no branch `feat/design-system-react-query-f1-f3` (`3399587`); backend reagendar mergeado em `main` (PR #2).
> **✅ DEPLOYADO em produção 2026-06-26 16:43** (containers healthy). Pendência git: mergear o branch frontend no `main`.
> Detalhes/convenções em `barbearia-frontend/AGENTS.md` (roadmap F1–F4) e `PROJECT_CONTEXT.md §0.0`.

- **F1 Fundação:** tokens (globals.css), `components/patterns` (Loading/Skeleton/Empty/Error/**AsyncState**), React Query (provider + `useAuthedQuery`).
- **F2:** 6 telas migradas p/ React Query + componentes de domínio + página enxuta (clientes, serviços, equipe, financeiro, dashboard, barbeiro) + polimento (KPIs com ícone, subtítulos).
- **F3:** CRM (1389 ln) → **Inbox em `/admin/conversas`** (SSE no cache RQ) + CRM **só funil**; Agenda admin (720 ln) → **grade do dia por profissional** (encaixe 1 clique, ações no bloco, atalhos, filtro, resumo) + **DnD reagendar (inclusive entre profissionais)**.
- **Primitivos `ui/`:** SegmentedControl, StatCard, Panel/SectionTitle (`section.tsx`), InitialAvatar. Sidebar: badges falsos removidos.
- **Backend (D-43):** `PATCH /agenda/{id}/reagendar` aceita `barber_id` (troca de profissional: revalida serviço↔profissional + conflito no novo barbeiro; `AppointmentOut` expõe `barber_id`). Testes em `tests/test_e2e_flow.py`.
- **Validado no browser** (extensão Chrome) contra o staging (org 1): criar/concluir+pagamento/cancelar/encaixe/filtro/DnD entre profissionais (e revert no 422). **Staging subido p/ migration `0011`.**
- Dívida anotada: drag reverte **silencioso** em erro (falta toast); detalhe cosmético de tempo relativo no Inbox resolvido.

---

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

## Pendências prioritárias (2026-06-26, 3ª)

- [ ] **[CRÍTICO] Migrar WhatsApp p/ Cloud API** (D-41) — bot não entrega; número restrito. Ver BLOQUEIO Nº 1.
- [x] **F1–F3 + reagendar DEPLOYADOS** na VM (2026-06-26 16:43, containers healthy). Verificado: Inbox/`barber_id` live.
- [ ] **Mergear o frontend F1–F3 no `main` do repo frontend** (`feat/design-system-react-query-f1-f3` → `main`)
      — higiene git: produção já roda esse código, mas o `main` do frontend ainda é `f5397a8`.
- [x] **Tela `/admin/empresa` (D-45)** — cadastro + endereço/horário + plano (read-only). Backend `empresa.py`
      + migration `0014` (aplicada no staging). 230 testes pass / 3 ambientais. **Falta:** deploy na VM
      (migration 0014 via `ADMIN_DATABASE_URL`) + verificação no browser.
- [ ] **(opcional) Toast de erro no drag da Agenda** — hoje o reagendar inválido (serviço não executado/conflito) reverte silencioso.
- [ ] **Fase 1.3 — limpar histórico git** de `credentials.json` (`git filter-repo` + force-push). Seguro
      agora (chave já revogada).
- [ ] **HTTPS + domínio** — nginx pronto; falta registrar domínio + certbot. Depois mover 8000/3000 p/ trás do nginx.
- [ ] **Reconciliar `docker-compose.yml`** repo vs VM (VM fixou Evolution na digest 2.3.7; repo tem `:latest`).
- [ ] **Backup automatizado** dos volumes/DB Docker · **auto-restart da VM** (WhatsApp cai quando a VM reinicia).
- [ ] **Frontend git remoto** — remote morto (`DoctorDCombo/...`); mover p/ repo vivo (risco de perda de histórico).
- [ ] **`workflows.json` local diverge da VM** — exportar da VM antes de editar.

> Frentes de produto saudáveis para avançar em paralelo (ver `CLAUDE.md` §8): **Frontend F1–F3 ✅ concluído**
> (falta mergear/deployar). Próximo no frontend: **F4 — acessibilidade + polish**. Produto: Caixa,
> Pacotes/Assinaturas, Dashboard executivo, Estoque/Consumo.

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
