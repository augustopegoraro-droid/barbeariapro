# CLAUDE.md — Memória Técnica do Projeto

> **Fonte de verdade técnica viva.** Atualize continuamente a cada decisão arquitetural,
> padrão adotado, regra de negócio ou integração nova. Não duplique segredos aqui.
>
> **Idioma:** todas as respostas e documentação em **pt-BR**.
>
> Documentos complementares (não duplicar — referenciar):
> - `PROJECT_CONTEXT.md` — estado operacional verificado contra a VM de produção (acessos, containers, env, fluxos do bot).
> - `DECISIONS.md` — registro cronológico de decisões (D-01, D-14, D-18, D-29, D-35...).
> - `CURRENT_SPRINT.md` — sprint corrente.
> - `barbearia-frontend/AGENTS.md` — convenções do frontend (ler antes de mexer no Next.js).
> - `CHATWOOT_CLOUD_API_ARQUITETURA.md` + `CHATWOOT_FASE1_FASE4_SPEC.md` — direção da camada de comunicação (D-49): Chatwoot + WhatsApp Cloud API.
> - `promptseguranca.md` — prompt master da iniciativa de Segurança/Governança (Fases 0-8 prontas, ver §6/D-67…D-74).
> - `FASE9_REVISAO_FINAL.md` — checkpoint final: checklist V1-V29, matriz papel×permissão, runbook, ADRs, rollout.
> - `promptsitepublico.md` — prompt master do site público de agendamento do cliente final. **✅ v1 DEPLOYADA em prod 2026-07-17 (D-79)**: apex `taylorethedy.com` = site público (`barbearia-public/`, :3200); `app.taylorethedy.com` = portal da equipe (D-78 executado; `taylor.` → 301). Fase 0 → `AUDITORIA_SITE_PUBLICO.md`; Fase 1 → `ARQUITETURA_SITE_PUBLICO.md`. v1 SEM OTP (WhatsApp restrito D-41): sessão de cookie 400 dias que só vê o que ela mesma criou; OTP entra com a Cloud API (`verified_at` já existe). Detalhes na D-79.
> - `/Users/apleandro/.claude/plans/partitioned-greeting-stearns.md` — auditoria completa + plano de evolução (origem deste arquivo).

---

## 0. Graphify — knowledge graph do código (OBRIGATÓRIO)

O knowledge graph do projeto vive em `graphify-out/` (skill `graphify`, `~/.claude/skills/graphify/SKILL.md`).
Regras permanentes de fluxo de trabalho:

1. **Antes de responder qualquer pergunta sobre o código ou de fazer qualquer alteração**, consultar
   primeiro o graphify (query no grafo em `graphify-out/`) para se contextualizar sobre arquitetura,
   arquivos e relacionamentos — só então ler os arquivos necessários e executar a tarefa.
2. **Depois de qualquer alteração no código** (criar/editar/remover arquivos, migrations, rotas,
   serviços, frontend), atualizar **automaticamente e sem pedir permissão**:
   - o **graphify** (reindexar/incorporar as mudanças no grafo), e
   - este **`CLAUDE.md`** (se a mudança tocar arquitetura, regra de negócio, convenção ou pendência).
3. Essas duas atualizações fazem parte da definição de "tarefa concluída" — junto com rodar os testes
   (ver rodapé deste arquivo). Não encerrar uma tarefa de código sem elas.

---

## 1. Visão do produto

**BarbeariaPro** está sendo evoluído para uma **plataforma SaaS multi-tenant** de gestão para
empresas de serviços baseadas em agendamento (barbearias, salões, estética, esmalterias, clínicas,
consultórios, pet shops...). Cliente âncora em produção: **Barbearia Taylor & Thedy** (Palmas/TO),
com clientes reais. A marca migrará gradualmente de "BarbeariaPro" para **"Taylor & Thedy"** sem
quebrar compatibilidade.

- **Usuária principal:** Raquel (recepcionista). Todo fluxo prioriza velocidade, simplicidade,
  poucos cliques e produtividade. Ela deve operar praticamente todo o negócio pelo sistema.
- **Objetivo:** centralizar tudo num só lugar — Agenda, CRM, Clientes, Financeiro, Caixa, Estoque,
  Produtos, Serviços, Profissionais, WhatsApp, IA, Marketing, Relatórios, Fidelização, Assinaturas,
  Pacotes, Indicadores, Automação.
- **Princípios de engenharia:** evoluir em vez de reescrever; reutilizar código; preservar
  retrocompatibilidade; pensar em escala (milhares de empresas); apresentar plano e aguardar
  aprovação antes de mudanças estruturais grandes.

---

## 2. Arquitetura geral

Monólito modular em 3 camadas + integrações, rodando hoje numa **única VM GCP** (`34.95.199.134`).

```
Next.js 16 (frontend :3000)  ──JWT──►  FastAPI (backend :8000)  ──RLS──►  PostgreSQL 16 (:5432)
        ▲                                   ▲        │
        │ next-auth v5                       │        └─► Google Calendar (OAuth, Fernet)
   nginx :80 (host da VM)                     │
                              X-Bot-Token / webhooks
                                             ▼
   WhatsApp ─► Evolution API (:8080) ─► /bot/wa-webhook ─► n8n (:5678) ─► OpenAI (GPT-4o-mini "Raquel")
```

### Stack
- **Backend:** Python 3.9 · FastAPI · SQLAlchemy 2 async (psycopg3) · Alembic · Pydantic v2 ·
  JWT HS256 (python-jose) · bcrypt · Fernet (cifra tokens OAuth) · httpx.
- **Frontend:** Next.js 16 App Router · TypeScript strict · Tailwind v4 · shadcn/ui v4
  (`@base-ui/react`, **não** Radix) · next-auth v5 (beta) · axios · `@tanstack/react-query`
  (instalado, **ainda não usado** — débito).
- **Dados:** PostgreSQL 16 com Row Level Security por `app.current_org_id`. ~27 tabelas.
- **Infra:** Docker Compose (`docker-compose.yml` = infra; `docker-compose.app.yml` = app) · nginx no
  host · n8n + Evolution API como serviços do bot. Detalhes operacionais em `PROJECT_CONTEXT.md §4`.

### Estrutura de pastas (backend)
- `app/api/*` — 19 routers (auth, agenda, barbeiro, bot, clientes, conversations, crm, dashboard,
  empresa, equipe, financeiro, health, integracoes, loyalty, memberships, reminders, servicos, wa_webhook).
- `app/core/*` — `config`, `security`, `rbac`, `crypto`, `dates`, `phone`.
- `app/services/*` — `scheduling`, `conversation`, `sse_broker`, `whatsapp`, `reminders`,
  `reactivation`, `loyalty`, `google_calendar`, `calendar_sync`, `membership`, `management`
  (camada de cálculo das *tools de gestão* — D-52, reaproveitada por bot/dashboard/cron).
- `app/db/session.py` — engine async + `set_current_org()` (ativa RLS por transação).
- `app/deps.py` — dependências de request (auth + sessão com tenant).
- `models/*` — modelos SQLAlchemy (organization, plan, subscription, unit, user, barber, client,
  appointment, payment, expense, service, lead, conversation, message, attachment, integration, membership, enums).
- `barbearia-frontend/` — **submódulo git separado** (remote `augustopegoraro-droid/barbearia-frontend`, privado; D-08).

---

## 3. Regras de negócio e fluxos atuais

### Autenticação / multi-tenant
- Login: `POST /auth/login {organization_id, email, password}` → `set_current_org()` **antes** de
  consultar (RLS) → bcrypt → JWT `{sub:user_id, org:org_id, exp}`.
- `get_tenant_db()` (`app/deps.py`) decodifica Bearer, abre transação e faz
  `SELECT set_config('app.current_org_id', :org, true)` (parametrizado, **local à transação** — não
  vaza no pool). **RLS é a única barreira multi-tenant.**
- RBAC por unidade: `owner > manager > reception > barber` (`app/core/rbac.py`).
- **Multi-tenant real (D-54, DEPLOYADO em prod 2026-06-30 — head `0021`; org 1 = `taylor`/`Barbearia`):** o `org_id` não é mais hardcoded.
  - **Login → subdomínio:** o frontend resolve o subdomínio do host (`taylor.app.com` → org) via
    `GET /auth/tenant?subdomain=` (público) e passa o `organization_id` ao `/auth/login`. `NEXT_PUBLIC_ORG_ID`
    vira só fallback de dev (localhost). Helpers em `barbearia-frontend/lib/tenant.ts`.
  - **Bot → instância WhatsApp:** `get_bot_db` resolve org/unidade pela instância (header `X-Instance`, enviado
    pelo n8n) e expõe via `get_bot_org_id`/`get_bot_unit_id`; sem mapeamento cai em `settings.bot_organization_id`
    (prod inalterado até backfill). **Não** se resolve por telefone (`phone_e164` não é único).
  - **Resolução pré-tenant:** `organizations` tem RLS, então um SELECT sem tenant não vê nada → funções
    `SECURITY DEFINER` `app_org_id_by_subdomain`/`app_org_id_by_wa_instance` (migration `0020`) devolvem só o `id`.
    Wrappers em `app/services/tenant.py`. `management.py` segue sem `org_id` em parâmetro: a RLS é a barreira.
  - **CORS multi-tenant (D-66, 2026-07-06):** com um subdomínio por tenant, a allowlist fixa `CORS_ORIGINS` não
    escala — as chamadas do browser (fetch/axios) davam preflight **400** (o **login** escapava por rodar
    server-side no next-auth). Solução: `cors_origin_regex` (`app/core/config.py` → `allow_origin_regex` em
    `app/main.py`), em **OR** com a allowlist. Prod: `CORS_ORIGIN_REGEX=https://([a-z0-9-]+\.)?taylorethedy\.com`
    no `.env` da VM cobre o apex + qualquer subdomínio (`taylor.`/`org.`/`admin.`) **sem redeploy por tenant**.
  - **Arquitetura de domínios (D-78 — ✅ EXECUTADO em prod 2026-07-17, junto com o D-79):**
    `taylorethedy.com` (apex) = **site público do cliente final** (`barbearia-public/`, serviço `public`
    :3200); **`app.taylorethedy.com`** = portal de login de funcionários/donos/gerentes (org 1 tem
    `subdomain='app'` no banco); `taylor.taylorethedy.com` → **301** para `app.`. A regex de CORS já cobria
    tudo. Config nginx anterior salva na VM (`barbeariapro.pre-d79.bak`). Detalhe na D-78/D-79.
- Bot: header `X-Bot-Token` validado contra `settings.bot_api_key`. Webhook Evolution:
  `X-Webhook-Secret` (hoje opcional). Comparações de segredo são **tempo-constante** via
  `app.core.security.secrets_match()`.

## Painel de Plataforma (Superadmin)

Separado do painel de tenant. `platform_admins` é tabela própria, sem
`organization_id`. Guards de plataforma usam SECURITY DEFINER e nunca setam
`app.current_org_id`. Rota: `/superadmin` ou `admin.taylorethedy.com` — nunca
dentro do frontend de tenant.

**Detalhes de implementação (D-55, DEPLOYADO em prod 2026-06-30 — API-only; superadmin `augustopegoraro.apl@gmail.com`):**
- **JWT próprio:** `create_platform_token` (`app/core/security.py`) emite `typ="platform"`
  **sem `org`**. Isolamento bilateral: token de tenant (com `org`, sem `typ`) é
  rejeitado pelo guard de plataforma; token de plataforma (sem `org`) é rejeitado
  por `get_token_data` do tenant. Guard `require_platform_admin` (`app/api/platform.py`)
  revalida o admin via SECURITY DEFINER a cada request.
- **RLS bypass controlado:** `barber_app` é NOBYPASSRLS, então um SELECT cross-org
  sem tenant retorna 0 linhas. Migration `0021` cria `platform_admins` (sem RLS, sem
  GRANT direto a `barber_app`) + funções SECURITY DEFINER (login, exists, `list_orgs`,
  `active_org_ids`, `usage`, `create_org`) com `GRANT EXECUTE TO barber_app` (molde da `0020`).
- **Cross-tenant híbrido:** listagem/contagens/uso via SECURITY DEFINER; **MRR
  consolidado reusa `mrr()`** (`management.py`) iterando orgs em **sessões helper
  isoladas** — o endpoint nunca seta o GUC na própria sessão. Onboarding
  (`POST /platform/orgs`, `app/services/onboarding.py`) cria org via SECURITY DEFINER
  e semeia filhos (unidade/owner/serviços do `SERVICES_CATALOG`) numa sessão helper
  escopada — substitui o `scripts/seed.py` manual. 1º superadmin via
  `scripts/seed_platform_admin.py` (role dona).
- **Frontend do Superadmin (D-56, 2026-07-01):** app Next 16 em **repo separado**
  `augustopegoraro-droid/barbearia-superadmin` (2º submódulo do backend, em
  `./barbearia-superadmin`), consumindo `/platform/*` de prod. Telas: login, dashboard
  (2 MRR + uso por tenant), tenants (listar/suspender/reativar/editar), onboarding.
  next-auth Credentials → token `typ=platform`; **sem** org/subdomínio; porta dev 3100.
  Serviço `superadmin` no `docker-compose.app.yml` sob **profile `superadmin`** (não sobe no
  `up` padrão) + `Dockerfile` + server block `admin.taylorethedy.com`→:3100 em
  `deploy/nginx.conf` + `.env.superadmin.example`. **Domínio ativo em prod (D-64,
  2026-07-05):** `taylorethedy.com` + TLS coringa via Cloudflare DNS-01 (certbot por snap).
  **✅ ATIVADO em prod (2026-07-05):** container no ar via `docker compose --profile
  superadmin up -d --build superadmin` com `SUPERADMIN_API_URL=https://api.taylorethedy.com`
  no build; `https://admin.taylorethedy.com` responde `307`→`/login` com cookies next-auth.
  Deploy key SSH somente-leitura própria (`bsuperadmin_deploy`), mesmo molde do
  `bfrontend_deploy`. Detalhes em DECISIONS.md D-56.
- **Pendente:** mover portas 8000/3000 para trás do nginx e fechar acesso direto (débito de
  segurança, ver tabela de dívida técnica); saúde de bot ao vivo (conectado/restrito) exige
  Evolution API (hoje só o proxy `wa_instance_name`).

### Financeiro (`app/api/financeiro.py`)
- Receita = soma de `AppointmentItem.price_charged` de agendamentos `concluido`.
- Comissão = receita × `Barber.commission_pct`. Despesas via `Expense` (com `competence_month`).
- `Payment` é registrado **independente** do Appointment (sem vínculo transacional — débito conhecido).
- **Ainda não existe:** caixa (abrir/fechar), consumo de produtos/estoque, pacotes/assinaturas.

### Agenda (`app/api/agenda.py` + `app/services/scheduling.py`)
- Validação encadeada (client/barber/service/link barber↔service/preço variável) → normaliza UTC →
  detecta conflito (`barber_has_conflict` + `TimeOff`) → `pg_advisory_xact_lock(unit.id)` p/ numeração
  atômica → cria `Appointment` + `AppointmentItem` → background sync Google Calendar.
- Barbeiro só enxerga os próprios agendamentos.

### CRM
- **Kanban de leads** (`crm.py`): estágios `novo_contato → conversando → agendado → concluido/perdido`,
  com `LeadEvent` para auditoria.
- **Inbox conversacional** (`conversations.py` + `services/conversation.py` + `sse_broker.py`): SSE em
  tempo real; `Conversation`/`Message`/`Attachment`; idempotência por `(conv, wa_message_id, sender_type)`.
  Porta única de escrita: `app/services/conversation.py::record_message`.

### WhatsApp / Bot
- Evolution → `POST /bot/wa-webhook` → `record_message(client)` → SSE Inbox; em background encaminha
  ao n8n (retry 3×). n8n: debounce → AI Agent "Raquel" → Send Response (Evolution) → `POST /bot/messages`
  → `record_message(bot)`.
- Debounce/dedup **em memória** (`app/api/bot.py`) — não sobrevive a multi-processo (débito de escala).
- **Trava de disparo:** `app/services/whatsapp.py` não envia se `EVOLUTION_API_URL`/`INSTANCE_NAME`
  estiverem vazios (protege staging).
- Fluxo do bot, comandos n8n e reconexão de WhatsApp: ver `PROJECT_CONTEXT.md §11-13`.
- **🚧 Direção decidida (D-49, 2026-06-27):** esta camada será migrada para **Chatwoot (VM nova) +
  WhatsApp Cloud API oficial** (número novo dedicado). A Evolution sai do fluxo do bot (D-41: número
  restrito, conserto esgotado); a Inbox custom/SSE e as Fases 4/5/6 do CRM são aposentadas. O backend
  permanece o sistema de registro (funil/agenda/financeiro). Raquel vira Agent Bot do Chatwoot. Plano em
  `CHATWOOT_CLOUD_API_ARQUITETURA.md`. **Status: plano — nada implementado.**

### IA — diretriz vigente
- **Decisão (2026-06-26): evoluir a IA dentro do n8n** (AI Agent node + OpenAI), expandindo as *tools*
  REST do backend (`/bot/*`). **Não** construir camada de agentes no backend por ora.
- Visão futura (roadmap): "funcionária virtual" que opera o sistema por linguagem natural e uma
  **arquitetura de múltiplos agentes especializados** instanciados sob demanda (não ficam rodando):
  Agenda, CRM, Financeiro, Caixa, Estoque, Comercial, Marketing, WhatsApp, Fidelização, Relatórios,
  Administrativo, Configurações, IA Recepcionista, Supervisor, Auditor, Analytics, Segurança. Cada
  agente terá doc própria (nome, objetivo, responsabilidades, permissões, ferramentas, I/O, fluxos).

---

## 4. Convenções de código
- **Backend:** chamada a API entre serviços via `httpx`; SQL sempre parametrizado (nunca f-string com
  input externo); transação por request via `get_tenant_db`; segredos só de `settings` (env), nunca
  hardcoded; comparar tokens estáticos com `secrets_match()`.
- **Frontend:** padrão de chamada `authedApi(token).get/post(...)` de `@/lib/api`; tema dark fixo
  (classe `dark` no `<html>`), brand amber `#f59e0b`; `useSearchParams()` exige `<Suspense>` (preferir
  `window.location.search` em client components). Ler `barbearia-frontend/AGENTS.md`.
- **Geral:** reutilizar componentes/serviços; evitar duplicação; manter tipagem; documentar decisões
  importantes em `DECISIONS.md` e aqui.

---

## 5. Segredos e segurança (regras)
- Credenciais (n8n, Evolution, OpenAI, Google, DB, JWT) são **segredos**: nunca expor em respostas,
  logs, docs, commits ou código. Usar apenas `.env*` (já cobertos pelo `.gitignore`).
- **Exposição conhecida:** `credentials.json` (blob n8n) entrou no histórico git (commit `657096c`) e
  está no remote público — requer rotação + limpeza de histórico (Fase 1.2/1.3).
- Os `.env*` com chaves de alto valor **nunca foram versionados** (`.gitignore` cobre `*.env`,
  `*credential*.json`, `backup-*.json`).

---

## 6. Funcionalidades — implementado vs. pendente

**Implementado:** Login/RBAC · Agenda (CRUD + conflito + Google Calendar) · Clientes/CRM Kanban ·
Inbox WhatsApp em tempo real (SSE) · Financeiro (resumo diário/mensal, despesas, comissões) ·
Serviços · Equipe · Integrações (WhatsApp status/QR, Google Calendar OAuth) · Bot IA "Raquel" (n8n) ·
Lembrete 24h e reativação de clientes · **Mensalidade/Assinatura do cliente final** (planos de catálogo
+ **pacotes personalizáveis por cliente** com combo/usos/preço/duração livres, `plan_id` nullable;
vigência, venda, **renovação clonando o snapshot**, expiração; receita rateada no uso. Consumo flexível:
agendar o combo, **usar agora** (avulso), ou **pagar com a assinatura no checkout**/anexar a um
agendamento existente. Combo de **catálogo** restrito a corte/barba/corte+barba — ver D-44/D-48).
**Correção/reversão (D-51, DEPLOYADO em prod 2026-06-28, head `0018`):** reativar (desfaz cancelamento na vigência), editar
(`PATCH`)/excluir (`DELETE`) venda **sem uso**, **estornar uso** de atendimento concluído pago por assinatura;
`renew` fecha a anterior (≤1 ativa); auto-pick 409 em múltiplas ativas; `revert_usage` atômico + `FOR UPDATE`
na conclusão (sem Payment duplicado); status `vencida` derivado; auditoria `canceled_by`/`reverted_by`
(migration `0018`); recepção passa a listar planos.

**Fidelização por pontos** (D-50, **deployada em prod 2026-06-28**): ledger append-only
(`loyalty_point_ledger`) + tiers/regras configuráveis por org (`loyalty_tiers`/`loyalty_rules`) + resgate
gerando voucher (`loyalty_vouchers`); `client_loyalty.points_balance`/`current_tier_id` derivados. Ladder único
(Bronze0/Prata150/Ouro500/Diamante1000/Black2000), 1 pt/R$ + 10/visita, resgate 1pt=R$1. Tela `/admin/fidelidade`
(abas Clientes/Configuração). Rollout 100% aditivo (nivel/categoria + API legada mantidos). Migrations `0016`/`0017`
(head=`0017`). **Falta (PR-C):** badges/filtro de tier em Clientes + slice no Dashboard.

**Tools de Gestão ("Agente Gestor")** (D-52, Fases A+B+C — **só staging**): camada única
`app/services/management.py` em 3 canais — bot (`/bot/gestor/*`, gating por telefone), dashboard
(`/admin/gestor/*`, JWT+`require_manager_access`) e cron (`/internal/gestor/*` via `gestor_notify`).
Tools: `whoami`, `financeiro`, `ranking`, `inativos` (+`disparar`, reusa `reactivation.run`), `buracos`
(agenda ociosa), `ia-faturamento`, `mrr`; push: `resumo-diario` + `alertas` (meta/queda). Frontend:
página `/admin/gestor` (React Query). Migration `0019` (`users.phone_e164` +
`organizations.monthly_revenue_goal`); crons em `docs/GESTOR_CRON_N8N.md`. **Pendente:** deploy prod
(aplicar `0019`, popular telefone do gestor, cadastrar meta, criar crons no n8n, mergear frontend).

**Import de clientes da Trinks (D-56/onboarding, 2026-07-01 — tooling pronto, só backend):**
migration `0022` (`clients` ganha `email`/`birth_date`/`notes`, aditivo) + `app/services/trinks_import.py`
(parser latin-1/`;`/preâmbulo, dedup por telefone, `normalize_phone`) + `scripts/import_trinks.py`
(CLI `--org-id --file [--commit]`, dry-run padrão, **roda na VM** — 5432 fechada). Validado no arquivo
real: **2.911 importáveis** / 371 dups / 0 inválidos. Exports crus são **PII (LGPD) — no `.gitignore`,
nunca versionar**. Runbook em `docs/TRINKS_IMPORT.md`. Reset opcional: `scripts/reset_org.py` (apaga
dados operacionais + catálogos, preserva estrutura/integrações/assinatura; dry-run + `--confirm-name`).
> ✅ **DEPLOYADO em prod 2026-07-01:** `0022` aplicada; org 1 (`Salão de beleza Taylor e Thedy`) resetada
> (260 linhas fictícias) e **2.911 clientes reais importados** da Trinks (backup `~/pre_trinks_backup.sql`
> na VM). **Também importados 47 agendamentos de julho** (`import_trinks_appointments.py` +
> `trinks_appointments.py`, de-para de serviços + fuso; 45 clientes casados + 2 criados → 2.913 clientes).
> Próximos imports (estoque/pacotes/financeiro/marketing) virão depois, mesmo molde.
>
> **Rotas de self-service (D-56, `app/api/imports.py`):** `POST /admin/import/trinks/{clients,
> appointments,ranking,loyalty,debts}` (gestor; corpo = CSV bruto, sem multipart; `commit=false` dry-run →
> `commit=true` grava; RLS pela org do token). Parsers aceitam `bytes` ou path.
> **Ranking** (`trinks_ranking.py`): enriquece clientes (preenche email/nascimento faltantes por
> telefone, nunca sobrescreve).
> **Fidelidade (D-62, 2026-07-03)** (`trinks_ranking.py::sync_loyalty_from_ranking` + rota `/loyalty` +
> `scripts/import_trinks_loyalty.py`): semeia `client_loyalty` (última visita → `compute_status`) + pontos
> históricos no ledger (1 pt/R$ + 10/visita, D-50) a partir do mesmo ranking. Idempotente (pontos 1×/cliente
> por marcador de `reason`; snapshot reescrito). Bootstrap que **destrava a reativação** — sem isto
> `client_loyalty` só nasceria ao concluir atendimentos pelo sistema. **✅ DADOS EM PROD 2026-07-03 (org 1,
> via CLI):** 2.197 clientes únicos (640 ativos / 290 em risco / 1.267 inativos = **1.557 alvos de
> reativação**, antes 0); 965.181 pontos. Reativação **segue DESLIGADA** (número restrito D-41 exige Cloud
> API). O `CronReactivation1` do n8n já roda 1×/dia às 11h BRT — nada a ajustar. Código pendente de
> commit/rebuild (o sync rodou via CLI injetado no container; a rota `/loyalty` ainda não está no prod).
> **Débitos** (`trinks_debts.py` + migration `0023` `client_debts` +
> API `app/api/debts.py`: `GET /admin/debts`, `/summary`, `POST /{id}/pay|reopen`): contas a receber
> (não cabia em `payments`); casa cliente por nome, `client_id` nullable, idempotente.
> **Fechamento de caixa diário (D-59, 2026-07-02):** `trinks_cash_closing.py` + migration `0026`
> `cash_daily_closings` + `scripts/import_trinks_cash_closing.py` + rota
> `POST /admin/import/trinks/cash-closing`. Lê a 2ª tabela do export "Movimentação Financeira"
> (o "Resumo de Movimentação de Entradas e Saídas"; a 1ª tabela, pagamentos por comanda, é fora de
> escopo — exigiria agendamentos de todo o período). Upsert por `(org, dia)`, idempotente.
> **✅ DEPLOYADO em prod 2026-07-02:** migration `0026` aplicada (head `0026`) + 149 dias reais
> importados na org 1 (05/01–02/07/2026), totais conferindo com o relatório da Trinks. Ainda
> **não existe módulo de Caixa vivo** (abrir/fechar em tempo real) — isto é só o histórico
> migrado para consulta/relatório. **Consumo:** `GET /financeiro/caixa?month=` + card "Histórico
> de caixa" em `/admin/financeiro` (visão Mês) — **✅ DEPLOYADO em prod 2026-07-02**.
> **Pagamentos/Estornos (D-63, 2026-07-04 — ✅ DEPLOYADO em prod 2026-07-04, head `0035`):** o export
> "Pagamentos/Estornos" (`…26pagamentos.csv`) é o **pagamento por comanda** que o D-59 deixou fora de
> escopo. Não cabe em `payments` (exige `appointment_id`, ausente para o período; enum `PaymentMethod`
> não captura taxa de operadora/antecipação/parcela/conta). Decisão: **tabela analítica dedicada**
> `payment_transactions` (migration `0035`, RLS no molde da `0026`, **sem UNIQUE**) espelhando o export
> para relatórios (mix de formas, custo de cartão, recebíveis) — **não** toca em `payments` nem exige
> agendamento. `app/services/trinks_payments.py` (parser puro + `import_payments` idempotente por
> **substituição de período** de `movement_date`, não upsert — export sem chave única) + rota
> `POST /admin/import/trinks/payments` + `scripts/import_trinks_payments.py` (roda na VM) +
> `tests/test_trinks_payments.py` (8 testes). **Sem CHECKs** (≠ D-60: taxa de operadora e troco são
> legitimamente negativos). **PII minimizada (LGPD):** não guarda nome do cliente/quem fechou/comentário.
> **Validado em staging (head `0035`):** suíte 472 pass / 2 ambientais / 0 regressões.
> **✅ DEPLOYADO em prod 2026-07-04 (molde D-59):** PR #22 (merge `c050b0d`) → `0035` aplicada (head `0035`;
> backup `~/predeploy_d63_20260704_163707.sql`) → rebuild backend (`/health` ok) → import na org 1 de
> **3.714 transações** (05/01–03/07/2026; **R$ 414.137,15** pagos / **−R$ 6.823,55** de taxa de operadora),
> validado por `psql` independente, conferindo com a Trinks. CSV cru removido da VM (LGPD). **✅ Consumo no
> frontend — DEPLOYADO em prod 2026-07-06 (D-66):** aba **"Pagamentos"** (4ª visão do Financeiro, ao lado de
> `Dia · Mês · DRE`) via `GET /financeiro/pagamentos` — KPIs (recebido/custo de cartão/líquido/ticket médio),
> mix por forma de pagamento, custo de cartão por bandeira e recebimento mês a mês (barras + tooltip).
>
> **DRE mensal / histórico financeiro por competência (D-65, 2026-07-06 — ✅ DEPLOYADO em prod, head `0036`):** o
> export "DRE" (Demonstrativo de Resultado) da Trinks é a peça que faltava — a tabela `Expense` está vazia,
> então não havia histórico de custos/resultado. É uma **matriz pivotada** (linhas = itens, colunas = meses):
> receita por tipo + despesa por categoria/subgrupo (Fixas/Variáveis/Pessoal/Impostos/Outros) + resultado,
> desde mai/2020. É **competência** (accrual) — **não reconcilia 1:1** com `payment_transactions`/
> `cash_daily_closings` (recebimento). Decisão (molde D-59/D-63): **tabela analítica dedicada**
> `dre_monthly_lines` (migration `0035`→`0036`, RLS + GRANT ao `barber_app`), guardando **só as linhas-folha**
> (subtotais/totais recomputados → sem dupla contagem). CHECK só em `section` (receita|despesa); **sem CHECK
> de sinal** (contra-receitas negativas, ex.: "Consumo de Pré-pago") e **sem UNIQUE** (idempotência por
> **substituição dos meses** cobertos). `app/services/trinks_dre.py` (parser despivota meses + detecta
> subgrupos **estruturalmente** + **self-check** `checksum_ok` contra os totais do próprio arquivo) + rota
> `POST /admin/import/trinks/dre` + CLI `scripts/import_trinks_dre.py` (roda na VM, aceita vários arquivos) +
> leitura `GET /financeiro/dre?inicio=&fim=` (série mensal: receita, despesa por subgrupo, resultado, margem)
> + `tests/test_trinks_dre.py` (9, fixture **sintética** — DRE é P&L sensível). **Validado:** parser nos **6
> arquivos reais** → `checksum_ok` em **todos os 75 meses** (mai/2020–jul/2026, 2.752 linhas-folha, 5
> subgrupos); suíte **481 pass / 2 ambientais / 0 regressões**. **✅ DEPLOYADO em prod 2026-07-06** (PR #23,
> merge `6ab1a3e`; molde D-59/D-63): backup `~/predeploy_d65_20260706.sql` → `0036` aplicada (head `0036`) →
> import dos 6 arquivos na org 1 (**2.752 linhas-folha / 75 meses**, todos `checksum_ok`, `removed_existing=0`),
> validado por `psql` independente (isolamento RLS ok) → rebuild backend (`/health` ok, rotas no ar). CSV cru
> removido da VM (LGPD). **✅ Consumo no dashboard — DEPLOYADO em prod 2026-07-06** (frontend PR #5, merge
> `2665437`): 3ª visão do Financeiro (`Dia · Mês · DRE`) em `/admin/financeiro` consumindo `GET /financeiro/dre`
> — 4 KPIs (receita/despesa/resultado/margem), gráfico Receita×Despesa por mês (barras verde/vermelha, eixo de
> anos, tooltip), composição da despesa por subgrupo, detalhamento mensal e nota de competência; seletor 12/24
> meses/tudo (padrão 24m). `components/financeiro/dre-view.tsx` (novo) + React Query (`useFinanceiroDre`) +
> tokens `--chart-*` (gráfico/HBars à mão, sem lib; validado nos temas claro e escuro). Deploy só-frontend (sem
> migration): `git pull` na VM (ff `e985d85`→`2665437`) + rebuild `--build frontend`; smoke `/login` 200 +
> HTTPS `taylor.taylorethedy.com` 200 + bundle `.next` confere.
> **Drill-down por conta — DEPLOYADO em prod 2026-07-06 (D-66):** cada subgrupo da "Composição da despesa"
> virou **accordion** (abre as contas-folha ordenadas por valor) + card **"Top 10 maiores despesas"** do
> período (backend passou a devolver `despesas_por_item` no `GET /financeiro/dre`, aditivo).
>
> **Débitos de clientes — DESCARTADOS (D-65, 2026-07-06):** o dono confirmou que o export "Débitos" da Trinks
> é fonte **inválida**; sai do escopo (a tabela `client_debts`/migration `0023` segue existindo p/ orgs
> futuras — só a carga T&T é descartada). `client_debts` é tabela-folha (nada a referencia; `client_id` é FK
> opcional) → remover não cascateia. Sem rota de DELETE no app → `scripts/delete_org_debts.py` (molde
> `reset_org.py`: `barber_app`+RLS, dry-run, `--commit` exige `--confirm-name`). **✅ Verificado em prod 2026-07-06:
> 0 débitos na org 1 (a carga nunca chegou a produção — nada a remover).**

**Kernel IA + Gestão inteligente de equipe (D-57, 2026-07-02 — ✅ DEPLOYADO em prod 2026-07-02,
código + migrations `0024`/`0025`, head `0025`):**
- **Kernel IA = NAVEGADOR por linguagem natural (anti-alucinação):** `app/services/kernel_ia.py` +
  `POST /kernel-ia/query` — o LLM (Claude `claude-haiku-4-5`, `ANTHROPIC_API_KEY` — D-77, modelo
  barateado em 2026-07-31; era `claude-opus-4-8`, e OpenAI `gpt-4o-mini` até 2026-07-15) só escolhe uma rota de
  um **catálogo fechado** filtrado por papel (RBAC: barbeiro → só a própria agenda + tool
  `solicitar_remarcacao_turno`); mensagem templada + `action=navigate`/`route` → o frontend
  redireciona (FAB `kernel-ia-launcher.tsx` no admin). **Não responde dados no chat** — exceto a
  exceção controlada do D-58 abaixo.
- **Remarcação (migration `0024`):** `appointment_reschedule_requests` + `/remarcacoes` (barbeiro
  cria; gestor lista/conta/aprova) + sino `NotificationBell` no AdminHeader. Aprovar **não** move
  os atendimentos (follow-up).
- **Folha × receita recorrente (migration `0025`):** `barbers` += `work_model` (clt/mei/
  comissionado/aluguel_cadeira/hibrido), `monthly_cost`, `chair_rent`. `management.py`:
  `payroll_summary` + `recurring_coverage` (MRR × folha fixa líquida → covered/surplus).
  `GET /admin/gestor/folha` + painel "Folha × Receita recorrente" em `/admin/gestor`; formulário
  de equipe configura modelo/custos. Responde às perguntas do doc `gestaointeligente/`.

**Hardening de integridade das 0024/0025 (D-60, 2026-07-03 — ✅ DEPLOYADO em prod 2026-07-03, head
`0027`):** code review multi-agente das migrations 0024/0025 → migration **0027** (aditiva, só
constraints, `down_revision=0026`) com 4 CHECKs espelhados no ORM: `barbers_{monthly_cost,chair_rent}_nonneg`
(dinheiro ≥ 0), `reschedule_source_valid` (`source IN ('app','kernel_ia')`), `reschedule_period_order`
(`period_end > period_start`, tolerante a NULL). + guards de API em `reschedule.py`: `@model_validator`
barra período invertido (F1→422) e `?status=` normaliza vazio/sentinela→todos / inválido→422 (F5, nunca
`[]` mudo). **F8 também implementado** (code-only, logo após o deploy da 0027): desempate `id DESC` em
`list_requests` (`created_at` iguais em inserts da mesma transação ficavam com ordem indefinida). Testes:
+7 remarcação (F1/F5/F8) com **fixture autouse de limpeza** + 1 equipe (F7 custo neg→422); suíte
**408 pass / 2 ambientais / 0 regressões**. Backstop de DB provado via `barber_app`/RLS. **Deferidos
(decididos):** F2 (nunca REVOKE ALL SEQUENCES no downgrade), F4 (múltiplos pendentes por barbeiro é
intencional — sem dedup), F6 (manter `func.now()`). Deploy de prod: pré-audit = **0 violações** (tabela de
remarcação vazia), backup `predeploy_d60_20260703_112029.sql`; migration rodada montando o repo do host
(a imagem não copia `alembic/`) como superuser `postgres` (`env.py` lê `DATABASE_URL`; `ADMIN_DATABASE_URL`
ausente na VM → URL inline). Registro completo na D-60 (`DECISIONS.md`) e em `PROJECT_CONTEXT.md`.

**Agente financeiro no Kernel IA (D-58, 2026-07-02 — ✅ DEPLOYADO em prod 2026-07-02, backend
+ frontend; sem migration nova):** owner/manager (`MANAGER_ACCESS`) ganham a tool
`consultar_financas` (`topico` + `periodo`, catálogo fechado igual ao `navegar`) — responde no
chat um relatório financeiro REAL, sem reabrir a alucinação do D-57: os números vêm 100% de
`management.py` via `app/services/kernel_ia_finance.py` (texto pt-BR determinístico, o LLM nunca
os toca); só **1 frase de insight** por cima é gerada pelo LLM (2ª chamada, sem tools), grounded
num playbook curado (`app/data/finance_playbook.py`, heurísticas gerais de mercado, editável sem
tocar em código) + o próprio relatório, e passa por `kernel_ia_finance.guard_insight` — qualquer
número citado que não esteja no relatório real nem no playbook é descartado (fail closed).
Recepção e barbeiro seguem sem acesso a dados financeiros (regressão coberta em
`tests/test_kernel_ia.py`). `action=finance_answer` novo no contrato do endpoint; frontend só
precisou de `whitespace-pre-line` no balão + tipo do `action`.
> ✅ **RESOLVIDO em prod 2026-07-31 (chave) / 2026-08-01 (UI) — ver D-88** — voltou ao ar após 29 dias fora (desde
> 2026-07-02, quando a `OPENAI_API_KEY` da VM expirou; degradava com graça em `action=config`, sem 500).
> `ANTHROPIC_API_KEY` + `KERNEL_IA_MODEL=claude-haiku-4-5` provisionados em `/opt/barbeariapro/.env`
> pelo dono; `up -d backend` (sem rebuild). Validado: container healthy, `/health` 200,
> `/kernel-ia/query` 401 sem auth, e **chamada real ao LLM** pelo SDK dentro do container →
> `claude-haiku-4-5-20251001` respondeu (encerra a validação "LLM real" pendente desde o D-58).
> ⚠️ O **código** em prod ainda tem o default `claude-opus-4-8`; quem manda é a env var do `.env`.
> No próximo deploy de backend o default do repo (já `claude-haiku-4-5`) alinha os dois.
> **Histórico — resolução decidida (D-77,
> 2026-07-15): o Kernel IA migrou de provedor — OpenAI → Anthropic/Claude** (SDK `anthropic`
> substitui `openai` no `requirements.txt`). **Modelo default `claude-haiku-4-5` desde 2026-07-31**
> (era `claude-opus-4-8`): a tarefa é escolher 1 rota de catálogo fechado + 1 frase sob guardrail —
> Haiku dá conta a $1/$5 por MTok (5× mais barato). Escalar por env (`KERNEL_IA_MODEL`) para
> `claude-sonnet-5` → `claude-opus-5` **se** a escolha de rota errar demais; sem deploy de código.
> Só a camada de provedor mudou — catálogo fechado, mensagens templadas, `guard_insight`,
> `redact_for_llm` (V15) e RBAC intactos; contrato do endpoint inalterado (frontend sem mudança).
> Suíte 589 pass / 2 ambientais / 0 regressões. **✅ DEPLOYADO em prod 2026-07-15** (backend
> `5cea9af`; backup `~/predeploy_d77_*.sql`; `anthropic 0.116.0` na imagem, `openai` removido;
> `/health` 200, `/kernel-ia/query` 401 sem auth). **Falta só:** provisionar `ANTHROPIC_API_KEY`
> em `/opt/barbeariapro/.env` (criar em console.anthropic.com; `up -d backend` recarrega, sem
> rebuild) + validação manual "LLM real" (pendente desde o D-58). A `OPENAI_API_KEY` da VM
> continua existindo só para o n8n (Raquel — não migrada).

**Painel SuperAdmin completo + Billing (D-61, 2026-07-03 — ✅ DEPLOYADO EM PROD, head `0034`):**
missão autônoma implementou M1–MF do painel de plataforma (dashboard executivo,
central de operações, gestão/detalhe 360° de barbearias, onboarding derivado,
billing Stripe via `BillingProvider` desacoplado + mock, assinaturas/dunning,
impersonação auditada, configurações) — migrations `0028`–`0034` aplicadas em STAGING e PROD (head `0034`). Fonte de verdade da missão:
**`docs/superadmin/`**. Envs novos de billing no `Settings`; dep `stripe`.

**Segurança / Governança — RBAC por permissões (D-67, Fase 2 — ✅ DEPLOYADO em prod 2026-07-07):** iniciativa
`promptseguranca.md` (9 fases c/ checkpoints). Fase 0 → `AUDITORIA_SEGURANCA.md` (29 achados); Fase 1 →
`ARQUITETURA_ALVO.md`. Fase 2 entregou o **núcleo de autorização baseado em permissões nomeadas**: catálogo em
código (`app/core/permissions.py`, 58 permissões × 9 papéis de sistema), migration **0037** (`permissions`/`roles`/
`role_permissions`/`user_roles`/`permission_overrides`, RLS), resolver (`app/services/authz.py`), guard central
(`app/authz.py::require`) + `GET /auth/me/permissions`. Corrigiu **V4/V5/V6/V7/V19** da auditoria (recepção deixa de
ver financeiro no dashboard; QR do WhatsApp e bot-pause exigem permissão; SSE revalida usuário+RBAC; bot token
tempo-constante). Retrocompatível: os 4 papéis atuais mapeiam 1:1. **F2.5 ✅:** ~90 call-sites legados migrados para
`require_permission` em 15 routers (mapeamento não-regressivo por conjunto-de-papéis idêntico; só `billing.py`
ficou no guard legado); teste de cobertura garante que toda rota de tenant tem auth. Suíte **526 pass / 2
ambientais / 0 regressões**. **F2.6 (frontend) ✅:** `hooks/use-permissions.ts` (`usePermissions().has()` via
`/auth/me/permissions`) → sidebar filtrada por permissão + identidade real (rodapé/avatar, antes hardcoded) +
botão "Conectar WhatsApp" gateado (V6). Typecheck limpo. **✅ DEPLOYADO em prod 2026-07-07** (backend `bf2acb2` + frontend `8535796`; migration `0037` head
`0037`; catálogo 59/9/251; validado: owner=59 perms, barbeiro=4; rotas 401/200 + HTTPS OK). Impacto nulo (prod só
tem owner+barbeiro; 0 reception/manager). Migration/sync via repo do host montado (`scripts/` não vai na imagem;
PG via `host.docker.internal`). Backup `~/predeploy_d67_20260707_205028.sql`.

**Segurança / Governança — Sessão, dispositivos e hardening de autenticação (D-68, Fase 3 — ✅ DEPLOYADO em prod
2026-07-09):** access token curto (15min) + refresh token rotativo com detecção de reuso (tabela `sessions`,
migration **0038** head `0038`, `FORCE ROW LEVEL SECURITY` em todas as tabelas RLS); rate limiting+lockout de
login (Redis/slowapi, **novo serviço `redis` no stack**); headers de segurança + `/docs` desligado por padrão;
anti-enumeração; SSE do CRM trocou JWT-na-URL por ticket de uso único. `/admin/security/*` (gestor): reset
administrativo de senha (sem e-mail no stack) e revogação de sessões de outro usuário. **UI de gestor**
(`/admin/usuarios`, antes placeholder "em breve"): lista usuários da org + diálogos de sessões/reset de senha,
consumindo `GET /admin/security/{users,sessions}`. Self-service em `/admin/seguranca/sessoes`. Corrigido nesta
sessão: bug pré-existente que salvava o `repr()` Python do parsing de user-agent em vez de texto legível. Suíte
**546 pass / 2 ambientais / 0 regressões**; validado no browser (dev local) e em prod via smoke test HTTP (login
real com credencial de produção ainda não testado manualmente — recomendado). **✅ DEPLOYADO em prod 2026-07-09**
(backend `db828cf` + frontend `c453b47`, direto na main; molde D-60/D-67): backup
`~/predeploy_d68_20260709_034435.sql`, migration 0038 aplicada (FORCE RLS confirmado em 100% das tabelas),
serviço `redis` novo saudável, backend+frontend rebuildados, smoke test OK (headers, `/docs` 404, rotas novas
protegidas, refresh inválido devolve 401 e não 500). Detalhes em DECISIONS.md D-68.

**Segurança / Governança — Auditoria (D-70, Fase 4 — ✅ DEPLOYADO em prod 2026-07-09):**
`audit_logs` por tenant (migration `0039`, RLS+FORCE, append-only — só `SELECT`/`INSERT` para `barber_app`) com
`prev_hash`/`hash` encadeados (adulteração/remoção no meio quebra a cadeia seguinte) e retenção configurável por
org (`organizations.audit_retention_months`, purga via `SECURITY DEFINER` + cron interno `/internal/audit/purge`,
ainda sem agendamento no n8n). Emissão fire-and-forget (`app/services/audit.py`, Task própria — sem fila/worker
separado, débito documentado). O **guard central audita sozinho** toda negação (`app/authz.py`, cobre as ~90
rotas do D-67 sem tocar nelas); eventos obrigatórios instrumentados nos pontos críticos (login/logout, CRUD de
clientes, despesas/exports financeiros, assinaturas, conclusão/estorno de atendimento, config da empresa, QR do
WhatsApp, reset de senha/revogação de sessão). `GET /admin/security/audit` (timeline filtrável) +
`GET /admin/security/audit/export.csv` (audita a si mesma), atrás de `security.audit.view`/`security.audit.export`
(já existiam no catálogo desde o D-67). Frontend: `/admin/seguranca/auditoria` + item novo na sidebar. Suíte
564 pass / 2 ambientais / 0 regressões; validado no browser (dev local). Detalhes em DECISIONS.md D-70.

**Segurança / Governança — Painel de segurança para gestores (D-71, Fase 5 — ✅ DEPLOYADO em prod 2026-07-09):**
dashboard construído inteiramente sobre `audit_logs` (D-70) — sem migration nova. Backend
`app/services/security_dashboard.py::dashboard_summary` (7 cards, série diária logins×negados por fuso local,
top ações negadas, últimas negações) + alerta de anomalia (negações de hoje ≥ máx(5, 3× média dos 7 dias
anteriores)). `GET /admin/security/dashboard?days=` reaproveita `security.audit.view` (sem permissão nova).
Frontend: `/admin/seguranca` (StatCards + gráfico CSS puro, molde DRE do Financeiro) + item "Segurança" na
sidebar. Rota backend validada via `curl`; validação visual no browser ficou pendente por falha da própria
ferramenta de automação. **Achado importante desta fase:** deadlock real em testes (Task fire-and-forget de
auditoria + `DELETE` síncrono na mesma linha `users`/`organizations` = thread bloqueada esperando um lock que só
o próprio event loop bloqueado poderia liberar) — corrigido com fixture `autouse` em `tests/conftest.py` +
`await` explícito nos 3 pontos de risco identificados; não afeta produção (um único event loop de vida longa).
Suíte 576 pass / 2 ambientais / 0 regressões reais. Detalhes em DECISIONS.md D-71.

**Segurança / Governança — Visibilidade do site público (D-73, Fase 6 — ✅ DEPLOYADO em prod 2026-07-15, junto
com D-74/D-76):**
`client_visibility_settings` (migration `0041`, 1:1 por org, RLS+FORCE) guarda a CONFIGURAÇÃO de serviços/
profissionais/horários/avaliações/promoções/banner/dados públicos exibidos — o site público em si **ainda não
existe** no produto (decisão combinada: construir só a configuração, sem endpoint público de leitura, que fica
para quando o site entrar no roadmap). `GET/PUT /admin/security/site-visibility` reaproveita
`security.site_visibility.manage` (já no catálogo desde o D-67). Frontend `/admin/seguranca/visibilidade` +
item na sidebar. Suíte 582 pass / 2 ambientais / 0 regressões. Detalhes em DECISIONS.md D-73.

**Segurança / Governança — Direitos do titular + histórico de consentimento (D-74, Fase 8 — ✅ DEPLOYADO em prod
2026-07-15, junto com D-73/D-76):** escopo recortado (Fase 7/analytics e banner de cookies/Consent Mode ficam para quando existir site
público de verdade — ver `promptsitepublico.md`, ainda não iniciado). `consent_records` (migration `0042`,
append-only, molde `audit_logs`/D-70) evolui o opt-in/opt-out do WhatsApp (D-51) sem substituir `client_consents`.
`clients.anonymized_at` + `app/services/lgpd.py`: exportar dados do titular (JSON portável) e anonimizar PII
preservando agregados financeiros (`Payment`/`AppointmentItem` intocados). Ações gestor-assistidas (sem portal do
cliente final ainda) em `app/api/lgpd.py`, gated por `privacy.lgpd.manage` (owner-only no catálogo desde o D-67).
Frontend: 2 ações novas no menu de cada cliente (Clientes), sem tela dedicada. Suíte 589 pass / 2 ambientais / 0
regressões. Detalhes em DECISIONS.md D-74.

**Segurança / Governança — Fase 9: revisão final + fechamento em lote (D-75/D-76, 2026-07-13/14 — ✅ DEPLOYADO
em prod 2026-07-15):** checkpoint obrigatório do
`promptseguranca.md` (`FASE9_REVISAO_FINAL.md`, checklist V1-V29 verificado no código real, não no plano — D-75)
seguido do fechamento dos achados de baixo risco sem dependência externa (D-76). **V1 (Crítica) resolvido em
produção sem deploy de código:** `WA_WEBHOOK_SECRET` configurado nos dois lados (VM + Evolution API), testado
ao vivo (sem/errado→401, correto→200) — o código já era fail-closed, o achado sempre foi de config de infra.
**Fixes de código (migration `0043`, commitados):** V14 (`mask_phone` em todos os logs com telefone), V15
(`redact_for_llm` tira nome de cliente do prompt ao OpenAI, sem tocar no relatório real do gestor), V16
(`platform_*` explicitamente revogado do `barber_app` em `scripts/setup_local.sh`), V17 (`appointment_items`
ganha `organization_id` denormalizado + RLS + `FORCE`), V18a (`webhook_events` RLS "global OU tenant"), V25
(`typ=oauth_state` dedicado no state OAuth do Calendar), V26 (bind parameter nos 3 advisory locks, era
f-string), V28 (`create_coupon` só trata `IntegrityError` como 409, não qualquer exceção). **V18b (`coupons`)
tentado e revertido:** revogar escrita quebrou o resgate real de cupom em staging — `barber_app` é o ÚNICO papel
de DB para toda rota (tenant e plataforma), sem um papel elevado separado como `platform_admins`/
`platform_audit_log` (que usam `SECURITY DEFINER`, D-55); corrigir de verdade exige o mesmo molde, fora de
escopo — **V18b segue aberto**. **Achado colateral do V18a:** RLS acessada por sessão sem tenant (`_mark_webhook`)
precisou de `NULLIF(current_setting(...), '')::bigint` — GUC local reverte para string vazia (não NULL) numa
conexão pooled reaproveitada, `''::bigint` estoura erro; só aparecia sob suíte completa (conexões reaproveitadas),
nunca isolado. **V20 adiado conscientemente:** depende do n8n (workflow na VM) passar `X-Instance` ao debounce
— hoje não passa; corrigir só o backend não muda nada. Suíte 589 pass / 2 ambientais / 0 regressões, confirmado
limpo em 2 execuções consecutivas. **✅ DEPLOYADO em prod 2026-07-15** (backend `51f6125`, molde D-59/D-63/D-65/
D-67/D-68): backup `~/predeploy_d76_20260715_024101.sql` → deploy único combinando D-73 (migration `0041`) +
D-74 (migration `0042`) + D-76 (migration `0043`) → rebuild backend. Validado: `appointment_items` 115/115
com `organization_id`; RLS+FORCE ativos em `appointment_items`/`webhook_events`; `/health` 200; rotas novas
protegidas (401, não 404/500); `coupons` confirmado com GRANTs intocados (V18b nunca chegou a tocar a tabela).
Com a iniciativa formalmente fechada, restam só itens de decisão do dono como débito consciente (V22 CORS, V27
Fernet, V29 histórico git, V18b coupons). Detalhes completos em DECISIONS.md D-75/D-76.

**Site público de agendamento do cliente final (D-79 — ✅ DEPLOYADO em prod 2026-07-17, apex
`taylorethedy.com`):** app novo **`barbearia-public/`** (Next 16, :3200, PWA instalável, mobile-first, pasta
no repo do backend — não submódulo) + backend `app/api/public.py` (`/public/{subdomain}/…`: vitrine gateada
pelo `client_visibility_settings`/D-73 com cache Redis 60s, slots livres via `app/services/availability.py`
[novo, reusável por painel/bot], sessão de cliente SEM OTP [cookie HttpOnly 400d, `client_sessions`,
migration `0044`], agendamento com a mesma validação do painel + `booking_channel='site'`, meus
agendamentos/cancelamento [>2h], logout; auditoria `actor_kind="client"`). **Sessão não verificada só vê o
que ela mesma criou** (`created_by_client_session_id`); `verified_at` reservado para o OTP futuro (Cloud
API). Lembrete 24h cobre agendamentos do site de graça. Suíte 603 pass. Envs novos na VM: `PUBLIC_COOKIE_DOMAIN`,
`PUBLIC_API_URL`, `PUBLIC_TENANT_SLUG=app`, `PUBLIC_SITE_URL`. Pendências: validação visual mobile real, OTP,
"meus dispositivos", fidelidade no site, logo real (lê `public_info.logo_url` quando existir). Ver D-79.
> **Hero cinematográfico com vídeo de drone (D-80, 2026-07-17/18 — ✅ DEPLOYADO em prod 2026-07-20, apex
> `taylorethedy.com`, commit `e29a9d6`):** a home abre
> com `components/hero-cinematic.tsx` (client) — vídeo de drone da barbearia em tela cheia com **scroll-scrubbing**
> (o vídeo "passa"/avança amarrado ao scroll via `currentTime`; wrapper `h-[200svh]` + camada `sticky h-[100svh]`;
> rAF sem lib; destrava iOS no 1º toque; respeita `prefers-reduced-motion`), **CTA "Agendar horário" premium**
> (`.cta-agendar` no `globals.css`: gradiente metálico prata escovada + glow pulsante + facho de luz + seta) na
> **faixa do polegar** durante todo o hero (conversão em 1º lugar; Serviços logo abaixo). Vídeo otimizado por
> ffmpeg do fonte 4K/1,1 GB (`VideoTa&TheDRONE.mp4`, a partir de 2:50, 14s sem áudio, 1280×720, **keyframes
> densos `-g 12`** p/ scrub fluido) → `public/hero-drone.mp4` **2,5 MB** + `public/hero-poster.jpg` ~100 KB
> (versionados; fonte cru no `.gitignore`). **Logo do topo = fachada real:** extraída do print oficial
> (`assets/images/taylor_thedy_logo.png`) por recorte → correção de perspectiva (warp PIL) → remoção do fundo
> marinho → `public/logo-lockup.webp` (transparente, cromado); `hero-cinematic.tsx` usa
> `<img src={logoUrl || "/logo-lockup.webp"}>` (o SVG `LogoLockup`/Optima do D-79 fica órfão). Tema grafite fixo.
> **Re-extração (2026-07-21):** a 1ª extração deixava halos brancos + risco preto e letras distorcidas ("não
> está igual à fachada"). Refeita: warp de perspectiva do campo navy (4 cantos → retângulo upright) + matte
> por **neutralidade (blue-chroma) × brilho** em vez de blue-key simples + despill azul + feather 0.6px +
> padding de respiro. Resultado limpo/fiel (77 KB, mesmo nome → sem mudança de código).
> Deployado (rebuild do serviço `public`, sem migration; backend recriado junto e voltou healthy). Falta só
> validação visual/scroll num celular real. Ver D-80.
> **⚠️ A "placa do t" NUNCA EXISTIU — premissa falsa, encerrada em 2026-07-24.** Várias sessões (2026-07-21
> a 24) trabalharam sobre a ideia de que a fachada teria uma *placa prata com um "t" escuro vazado*, e foram
> empilhando edições raster (aumentar a placa por replicação de borda, carvar um "lóbulo" no t, moldura fina,
> potrace) que só degradaram o asset — a versão local chegou a ficar com a placa quebrada, o "t" borrado e
> resíduo prata solto. **Zoom direto no original (`assets/images/taylor_thedy_logo.png`, região x 424-604 /
> y 250-497) prova que não há placa alguma:** o que foi lido como "caixa prata" é o corpo do **"T" maiúsculo
> serifado (Didot) de _Thedy_**, cromado e em relevo 3D, aplicado direto sobre o painel navy; o "t escuro"
> era o próprio painel visto entre a haste e a barra. **Não retomar essa linha.** As edições foram revertidas
> (`git checkout` do `logo-lockup.webp`) — o lockup vigente volta a ser a extração do D-80 (1000×472) e o
> `hero-plate.tsx` volta a `width/height = 1000/472`.
> **Símbolo "T" isolado (2026-07-24, local/não deployado):** com a fachada lida corretamente, o "T" foi
> extraído de verdade → `barbearia-public/public/symbol-t.webp` (513×600, ~21 KB, alfa). Pipeline:
> **medição da geometria real** (haste perfeitamente vertical em x≈499-523; horizontais convergindo à
> ESQUERDA — perspectiva de plano, sem rotação de câmera: topo da barra slope −0,237, base da serifa
> −0,148) → **homografia** (`Image.QUAD`, supersampling 3×) que aprumia a letra mantendo as verticais →
> **matte por neutralidade × brilho** (navy tem `b−r` alto, o cromado é neutro) + despill + feather →
> **isolamento por componente conexa** (BFS a partir da haste) para descartar o "or" e o "he" vizinhos.
> A extrusão 3D (sombra cinza colada à letra) é preservada de propósito — faz parte do letreiro real.
> **Ícones PWA regenerados** com esse símbolo (`icon-192.png`, `icon-512.png`, `apple-touch-icon.png`:
> quadrado navy `#1b2029` arredondado + T centralizado a 56%), substituindo a arte antiga que carregava
> justamente a "placa com t" inexistente. `sw.js` → `SW_VERSION = "v3-simbolo-t-2026-07-24"`.
> `public/icon.svg` e `public/logo-mark.svg` continuam com a arte antiga, mas **não são referenciados por
> nada** (o layout só declara `manifest`) — limpar quando conveniente.
>
> **Redesign UX/UI do site público (D-81, 2026-07-22 — ✅ DEPLOYADO em prod 2026-07-24, junto com o D-82):** rodada por equipe de
> agentes (UX + UI + Front-end); specs versionadas em **`docs/site-publico/`** (`UX_PLAN.md`, `UI_SPEC.md`,
> `FRONTEND_AUDIT.md` — fonte de verdade de UX/UI do site daqui em diante). P0 completo: bug do 409 (erro
> invisível ao voltar ao passo 3) corrigido; serviços da home clicáveis com pré-seleção `?servico=`; barra fixa
> de conversão pós-hero (`sticky-cta.tsx`); confirmação de cancelamento (bottom sheet) + toast; dias fechados
> desabilitados na régua via `info.hours`; alvos ≥44px. Fundação: `booking-flow.tsx` decomposto em
> `components/booking/*` + primitivos `components/ui/*`; tokens novos aditivos no `globals.css`. Débitos: hero
> `preload="metadata"`, ARIA/foco, tenant slug fallback unificado em `app`, `.dockerignore`, código morto do
> D-79 removido (`logo.tsx`/`logo-paths.ts`). Hero e `.cta-agendar` intocados; backend intocado. Build+tsc
> limpos. **Deployado junto com o D-82 (commit `455842d`).** P1/P2 do UX_PLAN ficam para
> próxima rodada; "reagendar com pré-seleção" exige backend (API devolve nomes, não ids). Ver D-81.
> **Fase 3 do D-81 (mesmo dia): pivô do dono — REVOGA o hero de vídeo do D-80 e o tema grafite.** Tema claro
> "A placa à luz do dia" (`docs/site-publico/UI_SPEC_V2.md`): página clara `#f5f6f8`, navy como tinta/assinatura,
> logo cromada só na faixa navy do topo (`components/hero-plate.tsx`, server/zero JS, headline "Renove seu
> estilo."), `.cta-agendar` = bloco navy metálico. `hero-cinematic.tsx` removido, `public/hero-drone.mp4`
> deletado do repo, `hero-poster.jpg` vira cartão-postal, SW com bump de versão. Fluxos/microcopy intactos.
> Ícones PWA ainda com arte antiga. Dev na rede local: `DEV_API_PROXY` (rewrite condicional no `next.config.ts`)
> + `API_URL_INTERNAL` + `NEXT_PUBLIC_API_URL=""` + `NEXT_PUBLIC_TENANT_SLUG=taylor` (dev DB usa `taylor`).
>
> **Landing page escura e dourada + a marca REAL da fachada (D-82, 2026-07-24 — ✅ DEPLOYADO em prod
> 2026-07-24, apex `taylorethedy.com`, commit `455842d`; REVOGA o tema claro do D-81/Fase 3):**
> ⚠️ **`assets/images/taylor_thedy_logo.png` é um MOCKUP GERADO POR IA,
> não é a marca** — ver `assets/images/README.md`. A marca real está em `assets/images/fachada-real.png` (foto do
> letreiro em Palmas) e a placa marfim com o **"t" vazado** já extraída com alfa em `public/t-fachada.png`
> (746×1334). O `logo-lockup.webp` que esteve **em produção até 2026-07-24** derivava do mockup → o site
> publicado exibia uma marca que não era a da barbearia; **o deploy do D-82 corrigiu isso** (o arquivo saiu do
> repo e responde 404). Fonte de verdade visual agora é
> **`docs/site-publico/UI_SPEC_V3.md`** ("A placa à noite, em ouro"): fundo `#0a0b0d`, marfim `#f2efe9`,
> **ouro `#c9a86a` como ÚNICA cor de ação**, Cormorant Garamond + Jost. O site inteiro (home, `/agendar`,
> `/meus-agendamentos`) é uma landing só: header fixo com CTA sempre visível, hero marca→promessa→prova→ação,
> serviços por categoria que já pré-selecionam, "Nossa casa" com fotos reais, depoimentos **verbatim** do Google
> (`components/depoimentos.tsx`; 4,8/400 avaliações, fonte `Avaliaçoesgoogle.pdf`), equipe, horários, fechamento.
> `.cta-agendar` mantém anatomia/timings congelados — só a paleta virou ouro. Ícones PWA/manifest refeitos com a
> placa real; `sw.js` → `v4-landing-ouro-2026-07-24`. Removidos os assets da linhagem errada (`logo-lockup.webp`,
> `symbol-t.webp`, `icon.svg`, `logo-mark.svg`) e o código morto (`hero-plate.tsx`, `logo.tsx`, `logo-paths.ts`).
> Deploy no molde D-79/D-80 (`git pull` na VM + rebuild do serviço `public`, **sem migration**; backend recriado
> junto e voltou healthy). Smoke OK: apex + `/agendar` + `/meus-agendamentos` 200, assets novos 200,
> `logo-lockup.webp` 404, `app.`/`api.` intactos. **Falta só validação num celular real** e confirmar o
> "25 anos" com o dono (não entrou por falta de fonte). Ver D-82.
> **Fix pontual (2026-08-01):** handle do Instagram em `lib/contato.ts` estava sem o `_` final
> (`taylorethedy` → `taylorethedy_`, perfil real da barbearia). Deploy só-frontend (molde D-79/D-80:
> `git pull` na VM + rebuild do serviço `public`, sem migration); validado em prod
> (`instagram.com/taylorethedy_`).

**Criação de usuário pelo gestor (D-83, 2026-07-29 — ✅ DEPLOYADO em prod 2026-07-29):** `POST /admin/security/users`
gated por `security.users.manage` (sem migration, sem permissão nova) — cria o login, grava o papel de sistema em
`user_units.role` (só `owner|manager|reception|barber`), opcionalmente vincula um `barber_id` (papel Barbeiro) e
devolve a senha inicial **uma única vez** (definida pelo gestor ou gerada), sempre com `must_change_password=True`.
Só o proprietário cria outro proprietário (403 — anti-escalada). Auditado (`security.users.create`). Frontend:
botão "Novo usuário" + `components/usuarios/create-user-dialog.tsx` em `/admin/usuarios`.
**+ `PATCH /admin/security/users/{id}`** troca o **e-mail** (credencial de login) de quem já existe — 409 em
duplicado, mesma regra anti-escalada para editar um `owner`, sem revogar sessões nem forçar troca de senha;
auditoria `security.users.update`. Frontend: botão "E-mail" na linha + `edit-email-dialog.tsx`. Suíte 614 pass.
> **Armadilha (corrigida em prod, frontend `e0dca66`):** `signOut({ callbackUrl })` do Auth.js atrás do nginx
> monta a URL absoluta a partir do request **interno** do container → mandava o usuário para
> `https://localhost:3000/login` ao fim da troca obrigatória de senha (bug pré-existente do D-68). Passar
> `Host`/`X-Forwarded-Host` não resolve. Padrão adotado: `signOut({ redirect: false })` + navegação **relativa**
> (`window.location.href`), que preserva o multi-tenant por subdomínio. Nunca voltar a usar `callbackUrl` aqui.

**Sincronização painel → site público (D-84, 2026-07-29 — ✅ DEPLOYADO em prod 2026-07-29, commit `7dcf304`,
sem migration):** cadastrar
profissional/serviço/horário no painel agora reflete na vitrine do apex **na hora**. Antes, três camadas
independentes seguravam a mudança: cache Redis de `GET /public/{sub}/info` (`public_info:{org_id}`, 60s), ISR do
Next (home 300s, `/agendar` 60s) e — latente — a whitelist `mode:"custom"` do `client_visibility_settings`
(D-73), que faria um cadastro novo nascer invisível **para sempre**. Porta única: `app/services/public_cache.py::
invalidate_public_info(org_id)` (apaga a chave do Redis + `POST {site}/api/revalidate` para expirar a tag
`public-info` do ISR), **sempre registrada em `BackgroundTasks`** — roda após a resposta, logo após o commit de
`get_tenant_db`, e nunca derruba a escrita do painel (falha = comportamento antigo). Call-sites: `equipe.py`
(criar/editar/arquivar barbeiro), `servicos.py` (criar/atualizar/arquivar/reativar), `empresa.py`
(`PATCH /empresa` + `PUT /empresa/horarios`), `security.py` (`PUT /admin/security/site-visibility`); folgas ficam
fora (afetam `/slots`, não cacheado). `site_visibility.py::ensure_visible` adiciona o cadastro novo à whitelist
quando ela existe — **cadastrar já publica**; para esconder, desmarcar em `/admin/seguranca/visibilidade` (no-op
em `mode:"all"`). No site: `lib/api.ts` tagueia o fetch (`INFO_TAG`) e `app/api/revalidate/route.ts` valida o
segredo em tempo constante, é **fail closed** (sem `REVALIDATE_SECRET` → 503) e está **bloqueado no nginx do
apex** (`deny all`) — só a rede interna do compose chega nele. Envs novas: `PUBLIC_SITE_INTERNAL_URL` +
`PUBLIC_REVALIDATE_SECRET` (o compose repassa como `REVALIDATE_SECRET` ao serviço `public`, mesma variável nas
duas pontas); vazias = só o Redis é invalidado. Suíte 619 pass (+5 em `tests/test_public_sync.py`). Em prod a
org 1 **não tem linha** em `client_visibility_settings` (tudo visível, `ensure_visible` é no-op) — a whitelist só
morde se o dono escolher `custom` na tela. Ver D-84.

**Foto do profissional + primeiro storage de mídia (D-85, 2026-07-29 — ✅ DEPLOYADO em prod 2026-07-29,
backend `ba3aee4` + painel `a9e86ae`, migration `0045`):**
`barbers.photo_path` guarda o **caminho relativo** (`org1/barber-7.webp?v=<mtime_ns>`), nunca a URL — a URL
pública é montada na leitura com `MEDIA_PUBLIC_BASE`, então trocar de domínio/storage não invalida o banco.
`app/services/media.py` é o storage (decisão do dono: **volume na VM**, não GCS nem campo de URL): descarta o
nome enviado (path traversal) e **sempre re-encoda em WebP quadrado 800px** — barra não-imagem, **apaga o EXIF**
(geolocalização, LGPD) e derruba 4 MB para ~60 KB; um diretório por org; escrita `.tmp`+`replace`; HEIC via
`pillow-heif` (foto de iPhone). Rotas `PUT|DELETE /equipe/barbeiros/{id}/foto` (`team.manage`, auditadas,
invalidam a vitrine do D-84). `/media` é servido pela **própria API** (`StaticFiles` em `app/main.py`) porque é
o único host que apex e `app.` alcançam em comum — no nginx só entra um `location /media/` com `expires 30d`
(seguro: a troca de foto muda o `?v=`). Frontend: `components/equipe/barber-photo.tsx` (painel: card + campo no
diálogo de edição, **só na edição** — o upload precisa do id) e `ProfessionalAvatar` do site público com
fallback de inicial (avatar cresce a 64px quando há foto). Infra: bind mount `./uploads:/app/uploads`,
`uploads/` no `.gitignore` (**PII**) e `.dockerignore`; **o container roda como não-root, então o diretório do
host precisa de `chown` para o uid do usuário `app`** (999 em prod) — senão o upload falha. **Pegadinha achada
no smoke de prod:** `python:3.12-slim` não tem `/etc/mime.types`, então sem `mimetypes.add_type("image/webp",
".webp")` (feito no `media.py`) o StaticFiles serve a foto como `application/octet-stream` — invisível em
macOS/Linux desktop. Suíte 635 pass (+16 em `tests/test_barber_photo.py`). Deploy transportado por **git
bundle** (GitHub inacessível do Mac na hora; **push ao remote segue pendente — a VM está à frente**). Ver D-85.

**LGPD — base legal na entrada, art. 18 de verdade e retenção (D-86, 2026-07-30 — ✅ DEPLOYADO em prod 2026-08-01, head
`0049`):** auditoria do schema/rotas contra os requisitos técnicos da lei. A Fase 8 (D-74) tinha a fundação;
faltavam as duas pontas. **Consentimento:** porta única `app/services/consent.py::set_consent` (estado
`client_consents` + histórico `consent_records` numa chamada) + `app/core/privacy.py::PRIVACY_POLICY_VERSION`
(carimbada em todo aceite; publicar texto novo e subir a constante **no mesmo commit**) + política publicada
em `barbearia-public/app/privacidade/page.tsx` (revisão jurídica pendente) + **aceite obrigatório** no
`POST /public/{sub}/auth/session` (422 sem ele) e opcional/default-true no `POST /clientes` (desmarcar =
opt-out). Antes disso o titular entrava na base **sem base legal nenhuma** pelo site e pelo painel — só o bot
registrava. **Art. 18:** export ganhou pagamentos/conversas/`message_log`/leads/sessões e passou a declarar
truncamento (`{total, truncado, itens}`, teto 5.000 — o `LIMIT 500` silencioso mentia por omissão);
anonimização passou a cobrir `Conversation`/`Message`/`Attachment`, `MessageLog`, `Lead` e `ClientSession`
(revoga + limpa IP/UA) — antes o titular seguia identificável pela própria conversa de WhatsApp. Preservados
de propósito: `payments`/`appointment_items` e `consent_records` (é a **prova**). **Auditoria:**
`verify_chain` + `GET /admin/security/audit/verify` (distingue `kind="link"` de `kind="payload"`) e
`clients.bulk_read` quando a listagem passa de 100 (exfiltração por usuário legítimo não deixava rastro).
**Retenção:** `GET/PUT /admin/security/retention` + purga de sessões (`app_sessions_purge_expired`, 0047) no
**mesmo** cron `/internal/audit/purge`. **Backfill:** `scripts/backfill_consent.py` (dry-run,
`--confirm-name`, idempotente) — **✅ EXECUTADO em prod 2026-08-01** com `--status opt_in` (decisão do dono:
"cliente de relacionamento anterior, migrado da Trinks"): **2.918 de estado + 2.918 de histórico**, 0 clientes
sem base legal (antes `client_consents` estava **vazia**); anonimizados ficam de fora de propósito.
**Decidido (dono, 2026-08-01): separar consentimento por finalidade** (transacional × marketing) **na
migração para a Cloud API** — hoje o SAIR desliga os dois, e quem só não quer propaganda perde o lembrete do
próprio horário.
> **🐞 Dois defeitos reais achados na implementação.** (1) **A trilha do site público nunca existiu:** o D-79
> emite `actor_kind="client"` e a CHECK da 0039 só admitia `user|bot|system` — como `record_event` é
> fire-and-forget e engole a exceção, todo evento do cliente final falhava em silêncio desde 2026-07-17
> (migration **0046** amplia a CHECK + teste de regressão). (2) **O banco reescrevia a tabela append-only:**
> `audit_logs.actor_user_id` tinha `FK ... ON DELETE SET NULL`, então apagar um usuário zerava o campo nas
> linhas antigas e o hash parava de bater — trilha "adulterada" sem adulteração (138 linhas no staging).
> Migration **0048** solta o FK: o id do ator é fato histórico, não referência viva. Linhas já zeradas são
> perda irrecuperável e a verificação continua apontando-as.
> **Não feito de propósito** (decisão do dono, não técnica): consentimento por **finalidade** (hoje é por
> canal — transacional e marketing compartilham o opt-in), exigir opt-in positivo para marketing (hoje o
> filtro é "não estar em opt-out"), prazo de descarte de dado pessoal do cliente, portal do titular
> (a sessão do site não é identidade verificada sem OTP). **Falta para prod:** aplicar 0046–0048, rebuild,
> **agendar `POST /internal/audit/purge` no n8n** (nunca rodou), rodar o backfill na org 1, revisão jurídica
> da política, telas de gestor para cadeia/retenção. Suíte **649 pass / 2 ambientais**. Ver D-86.

**Aceite de quem OPERA o sistema — termo do funcionário + contrato de operador/DPA (D-87, 2026-07-31 —
✅ DEPLOYADO em prod 2026-08-01, head `0049`):** o D-86 fechou a entrada do cliente final; funcionário e dono entravam no
painel sem aceitar nada. **Dois documentos com naturezas jurídicas diferentes:** (a) **termo de uso e
confidencialidade**, por usuário — **não é consentimento** (a base legal do vínculo é a relação de trabalho;
consentimento de empregado é frágil por desequilíbrio de poder), é o registro do dever de sigilo e do uso
auditado; (b) **contrato de operador/DPA**, por organização e **só o proprietário aceita** — a LGPD art. 39
exige instruções **documentadas** do controlador, e uma org nascia por `POST /platform/orgs` (D-55) já
operando sem contrato. Migration **0049** (aditiva): `users.terms_version_accepted`/`terms_accepted_at` +
`organizations.dpa_version_accepted`/`dpa_accepted_at`/`dpa_accepted_by_user_id` (**sem FK**, molde da 0048);
histórico em `consent_records` com `subject_type='user'` (valor já previsto no CHECK, nunca usado). Guarda a
**versão aceita**, não booleano → subir `TERMS_VERSION`/`DPA_VERSION` em `app/core/privacy.py` reabre o aceite
sem migration. API `app/api/legal.py`: `GET /auth/me/legal` + `POST /auth/me/legal/accept` (DPA → 403 para
quem não é owner; ambos auditados). Gate `components/legal/legal-gate.tsx` no `AdminShell` **e** no layout do
barbeiro (que não usa o shell): o `pending` vem da **API, não do JWT** — aceitar libera na hora sem novo login
(≠ `must_change_password`/D-68, que redireciona pelo `proxy.ts`). Textos em
`barbearia-frontend/lib/legal.ts`. **DPA revisado pelo dono em 2026-08-01 (v`2026-08-01`, em prod):**
isolamento vira "medidas adotadas" (não garantia), finalidades cobrem segurança/antifraude/obrigação legal,
subprocessadores sem promessa de aviso prévio, "trilha imutável" → "registros protegidos contra alteração não
autorizada", incidente "sem atraso injustificado", suporte a pedidos de titular, retenção pós-contrato
realista e **item 8 "Responsabilidades da Controladora"** (a barbearia declara ter base legal — impede que
atribua à plataforma um envio sem autorização). O termo do funcionário segue em `2026-07-31` e **quem já
aceitou não foi incomodado** — versionar por documento provou o desenho. **Política do site revisada em 2026-08-01 (v`2026-08-01`, em prod):** mesmas
correções — segurança vira "medidas adotadas" + "trilha protegida contra alteração não autorizada", SAIR
promete atualizar o cadastro (não bloqueio instantâneo), prazo de 15 dias só para confirmação/acesso e o
resto em prazo razoável, retenção com relacionamento encerrado + defesa em processo + **parágrafo sobre
backups** (sobrevivem à exclusão até a rotação) e ausência de rastreadores passa a valer "atualmente".
Subir `PRIVACY_POLICY_VERSION` **não** reabre aceite de ninguém (≠ termo/DPA): ela é carimbada em cada
consentimento novo e os já gravados guardam a versão que o titular viu.
> **Decisão explícita: o bloqueio é de UX, não de API** — as rotas de negócio seguem respondendo a token
> válido com aceite pendente. Travar tudo derrubaria a barbearia por um bug de tela, e o valor jurídico está
> no registro auditado. Se virar bloqueio real, o lugar é o guard central (`app/authz.py`), com exceção para
> as rotas de aceite.
> **Armadilha:** `get_tenant_db` abre a transação num context manager — consulta **depois** do `db.commit()`
> estoura *"Can't operate on closed transaction inside context manager"*. Montar a resposta antes do commit.
> Suíte **661 pass / 2 ambientais**. Ver D-87.

**Repasse de comissão entre barbeiros (D-89, 2026-08-02 — ✅ DEPLOYADO em prod 2026-08-02):**
`commission_transfers` (migration `0050`, molde `consent_records`/0042): repasse **vinculado a um
`AppointmentItem` já concluído** — o gestor lança que uma fração da comissão do dono do item vai para outro
barbeiro (atendimento a 4 mãos, acordo entre profissionais), sem mudar o dono do item nem `commission_pct` de
ninguém; `amount` é snapshot (não recalcula se o `commission_pct` mudar depois). `app/services/management.py`
ganha `commission_transfer_deltas`/`commissions_by_barber` — função única que aplica o delta líquido (soma
sempre zero) por cima de `receita × commission_pct`, substituindo a fórmula que estava duplicada em
`barber_ranking`/`financial_summary`/`payroll_summary`/3 rotas de `financeiro.py`. Permissão nova
`finance.commission_transfers.manage` (bloco `_FINANCE`, catálogo `app/core/permissions.py`) +
`POST /financeiro/appointment-items/{id}/repasse-comissao` + `GET/DELETE /financeiro/repasses`, auditadas.
Frontend: botão "Repassar comissão" nos atendimentos concluídos da visão Dia (`components/financeiro/
dia-view.tsx` + `repasse-dialog.tsx`) e seção "Repasses do mês" com estorno na visão Mês. Suíte
**667 pass / 2 ambientais / 0 regressões** (`tests/test_commission_transfers.py`, 6 casos); `tsc`/`eslint`
limpos. **✅ DEPLOYADO em prod 2026-08-02** (backend `d5e63ae` + frontend `22b6a70`; migration `0050` aplicada,
catálogo com 60 permissões, validado via login real + `/financeiro/repasses` + `/auth/me/permissions`).
**Incidente corrigido no próprio deploy:** combinar `docker-compose.yml` + `docker-compose.app.yml` no `up`
recriou `redis`/`backend` na rede docker errada (500 no login) — `docker-compose.app.yml` roda **sozinho**
(a infra é alcançada via `host.docker.internal`); nunca combinar os dois arquivos nesse stack. **Falta:**
validação visual no browser.

**Produtos/Estoque/Vendas — Fase 1: catálogo (2026-08-02 — implementado, só dev/staging):**
plano completo em `/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md`
(8 fases; venda vira entidade `Sale` própria e opcional ligada a `appointment_id`, sem tocar em
`AppointmentItem`/`Payment`; "integração com caixa" fica restrita a financeiro/relatórios enquanto não
existir caixa vivo). Esta fase entrega só o cadastro, sem estoque/venda ainda: `product_categories` +
`products` + `product_variants` (migration `0051`, molde `commission_transfers`/0050 — RLS+FORCE+GRANT
incl. UPDATE). Todo produto tem **pelo menos 1 variante** (produto "simples" ganha variante default
"Único" na criação) — preço/custo/estoque sempre pendura na variante, nunca no produto; isso evita caso
especial quando existe variação real (tamanho/sabor). `tracks_stock` no produto e `cost_avg`/`stock_qty`/
`min_stock` na variante já estão no schema desde já (ficam em 0/true sem uso) para a Fase 2 (Estoque) não
exigir migration própria para essas colunas. Permissões novas (`app/core/permissions.py`):
`products.view` (bloco `_OPERATIONS` → owner/manager/reception), `products.manage`/`products.cost.view`
(só owner/manager via `_ALL`/`_MANAGER`). Router `app/api/produtos.py`: CRUD de categorias (arquivar via
`PATCH .../categorias/{id}` com `active`), produtos (`POST /produtos` aceita `price` solto → cria variante
"Único", ou `variants[]` explícito) e variações (`POST /produtos/{id}/variacoes`,
`PATCH /produtos/variacoes/{id}`), auditado (`products.category.*`/`products.product.*`/
`products.variant.*`). Frontend: `/admin/produtos` (catálogo + painel de categorias inline) +
`components/produtos/` (molde `components/servicos/`; `produto-form-dialog.tsx` edita cadastro E
variações inline no mesmo diálogo) + `hooks/use-produtos.ts` + item "Produtos" na sidebar (grupo GESTÃO,
`perm="products.view"`). Suíte **682 pass / 2 ambientais / 0 regressões** (+16 em
`tests/test_produtos.py`: RLS, RBAC, CRUD, variante default). Validado end-to-end no browser (dev local):
criar categoria → criar produto → adicionar variação → arquivar → ver em "Todos" com badge → reativar.
**✅ DEPLOYADO em prod 2026-08-03** (migration `0051` aplicada, head `0051`; backend rebuildado; validado
`/health` 200 + rotas novas protegidas).

**Produtos/Estoque/Vendas — Fase 2: estoque e alertas (2026-08-03 — implementado, só dev/staging):**
`stock_movements` (migration `0052`, molde `commission_transfers`/0050 — **append-only**: só
`GRANT SELECT, INSERT` a `barber_app`, sem UPDATE/DELETE, mesma lógica de `audit_logs`). Enum PG
`stock_movement_type` já nasce com os 6 valores do plano completo (entrada_compra/entrada_ajuste/
saida_venda/saida_ajuste/perda/inventario) mesmo só emitindo ajuste/perda manuais nesta fase — evita
`ALTER TYPE ADD VALUE` (não roda na mesma transação que já usa o valor novo) nas Fases 3/6. Toda escrita
em `ProductVariant.stock_qty` passa exclusivamente por `app/services/inventory.py::apply_stock_movement`
(lock `FOR UPDATE` na variante, molde `barbeiro.py::_load_appointment`, bloqueia saldo negativo com 409).
`low_stock_alerts` no mesmo módulo. Router `app/api/estoque.py`: `GET/POST /estoque/movimentacoes`
(manual: entrada_ajuste/saida_ajuste/perda — perda exige motivo) + `GET /estoque/alertas`; produto sem
`tracks_stock` bloqueia movimentação (422). Permissões novas `inventory.view`/`inventory.manage` (bloco
`_OPERATIONS` → owner/manager/reception; ausentes do papel barbeiro). Frontend: `/admin/estoque` +
`components/estoque/` (molde `components/produtos/`) + `hooks/use-estoque.ts` + item "Estoque" na
sidebar (`perm="inventory.view"`). Suíte **694 pass / 2 ambientais / 0 regressões** (+11 em
`tests/test_estoque.py`: RLS, RBAC, saldo negativo→409, perda sem motivo→422, produto sem controle de
estoque→422). Validado no browser (dev local): produto criado, alerta de mínimo aparece corretamente.
**Achado do Select+Dialog (2026-08-03) — INVESTIGADO E DESCARTADO, não é bug real:** a sessão anterior
registrou (e depois retratou) uma suspeita de que escolher uma opção de `components/ui/select.tsx`
aninhado num `Dialog` fechava o Dialog inteiro. Investigação a fundo (event listeners instrumentados,
inspeção do hidden input do `@base-ui/react` Select, testes via mouse/coordenada e via teclado) mostrou
que o comportamento é **correto**: clicar no trigger duas vezes na MESMA coordenada é, na prática, abrir
e depois fechar o popup (a opção só fica alinhada exatamente sobre o trigger quando aberto —
`alignItemWithTrigger`), então repetir o clique no trigger em vez de mirar a opção reabre/fecha sem
selecionar. Clicando deliberadamente na **opção** (elemento distinto do trigger, confirmado via
`elementFromPoint`/hidden input), a seleção é aplicada corretamente e o Dialog permanece aberto — testado
com sucesso tanto no `MovimentacaoDialog` novo quanto no `ProdutoFormDialog` (categoria) já em produção.
A causa raiz da confusão original foi um descompasso de escala entre a screenshot da ferramenta de
automação (1456×829) e o viewport real (1512×861, DPR 2), que fazia os cliques por coordenada errarem o
alvo por alguns pixels. Mantido como melhoria de código (não como fix de bug): os arrays `items` passados
aos `Select` em `movimentacao-dialog.tsx` foram memoizados com `useMemo` (evita recriar o array a cada
render). **Não fechar** `components/ui/select.tsx`/`dialog.tsx` como pendência — não há ação a tomar.
**✅ DEPLOYADO em prod 2026-08-03** (backend+frontend `a4835c7`; migration `0052` aplicada, head `0052`;
backup `~/predeploy_d90_fase2_estoque_*.sql`; validado `/health` 200, `/estoque/movimentacoes` 401 sem
auth, `app.taylorethedy.com` 200).

**Produtos/Estoque/Vendas — Fase 3: venda de balcão com baixa automática (D-91, 2026-08-03/04 —
✅ DEPLOYADO em prod 2026-08-04, migration `0053` aplicada, head `0053`):** `sales`/`sale_items`/`sale_payments` (migration `0053`, molde `commission_transfers`/0050
— RLS+FORCE+GRANT incl. UPDATE, sem DELETE — é registro financeiro, nunca se apaga, só `cancelar`), par
paralelo a `Appointment`/`AppointmentItem`/`Payment` **sem alterar nenhuma delas**: `sales.appointment_id`
é opcional (`NULL` = venda de balcão pura; preenchido = anexada a um atendimento, sem tocar em
`AppointmentItem`) e `sale_payments` reaproveita o enum `payment_method` já existente. `SaleItem.
unit_price_charged`/`unit_cost_snapshot` são snapshots (preço/custo da variante no momento da venda, molde
`AppointmentItem.price_charged`/`CommissionTransfer.amount`). Baixa de estoque é **síncrona, na mesma
transação da venda** (`app/api/vendas.py::criar_venda` chama `apply_stock_movement` com
`movement_type=saida_venda`, `reference_type="sale"`) — produto sem `tracks_stock` não gera movimentação
nenhuma. `POST /vendas` valida que a soma dos pagamentos bate com o total calculado (preço da variante ×
qty de cada item) antes de gravar; saldo insuficiente estoura 409 vindo do próprio `apply_stock_movement`
(sem duplicar a checagem). `PATCH /vendas/{id}/cancelar` reverte o estoque (`saida_ajuste` com quantidade
positiva, motivo fixo "Estorno de venda cancelada") e marca `status="cancelada"` — nunca deleta linha;
cancelar 2× devolve 409. Permissões novas `sales.view`/`sales.create` (bloco `_OPERATIONS` → owner/
manager/reception) e `sales.cancel` (só owner/manager via `_ALL`/`_MANAGER` — a recepção vende mas não
cancela). Frontend: `/admin/vendas` (`components/vendas/`: `venda-rapida-dialog.tsx` com carrinho
multi-item antes de confirmar, `vendas-table.tsx` com badge de status + botão Cancelar gated por
`sales.cancel`) + `hooks/use-vendas.ts` + item "Vendas" na sidebar (grupo GESTÃO, `perm="sales.view"`).
Suíte **703 pass / 2 ambientais / 0 regressões** (+9 em `tests/test_vendas.py`: baixa de estoque, saldo
insuficiente→409, pagamento não bate→422, produto sem controle de estoque→sem movimentação, cancelar
estorna e cancelar 2×→409, venda anexada a atendimento sem alterar `Appointment`, RBAC, RLS). Validado
end-to-end no browser (dev local) + via API: criar produto → dar entrada de estoque → `POST /vendas` →
saldo desce na hora → tela `/admin/vendas` lista a venda → cancelar → estoque estorna e a UI atualiza
sozinha (React Query invalida `vendas`/`estoque`/`produtos`). **✅ DEPLOYADO em prod 2026-08-04**
(backend `4170ebb` + frontend `8581a8b`; backup `~/predeploy_d92_vendas_20260804_115032.sql` na VM;
migration `0053` rodada montando o repo do host no container `barbeariapro-backend` como superuser
`postgres`, molde D-60/D-90; `scripts/sync_authz_catalog.py` rodado — catálogo com 68 permissões/9
papéis/284 vínculos; rebuild `backend`+`frontend` via `docker compose -f docker-compose.app.yml up -d
--build`; validado `/health` 200, `/vendas` e `/estoque/movimentacoes` 401 sem auth,
`app.taylorethedy.com` 307→login, `taylorethedy.com` 200, logs do backend limpos). **Pendente:** Fases
5-8 do plano (fornecedores/compras, inventário, relatórios avançados, extensibilidade kits/combos/
cupons).

**Produtos/Estoque/Vendas — Fase 4: venda integrada à comanda + financeiro (D-91, 2026-08-03/04 —
✅ DEPLOYADO em prod 2026-08-04, junto com a Fase 3, sem migration própria):** bloco opcional **"+ Produtos"** dentro de
`components/agenda/concluir-dialog.tsx` (usado tanto pelo admin quanto pelo barbeiro, já que ambos
compartilham `ConcluirDialog`/`useConcluirAtendimento`): ao confirmar, se o carrinho de produtos tiver
itens, `POST /vendas` roda **antes** de `useConcluirAtendimento` (com `appointment_id`/`client_id` do
atendimento), sem alterar esse hook nem `AppointmentItem`/`Payment` — exatamente o desenho do plano.
Gated por `usePermissions().has("sales.create")`; forma de pagamento do produto é escolhida à parte
(não precisa ser a mesma do serviço, e continua funcionando mesmo quando o atendimento é pago via
assinatura, que não cobre produto). Extraído `components/vendas/produto-picker.tsx` (seletor produto→
variação→quantidade+"Adicionar ao carrinho", sem estado de carrinho) para ser **compartilhado** entre
`venda-rapida-dialog.tsx` (balcão) e o novo bloco da comanda — exatamente o "produto-picker
compartilhado com a comanda" do plano original.

**Backend:** `app/services/management.py::product_sales_summary(db, date_from, date_to)` — nova função
pura (mesmo molde das demais do módulo, reusável por bot/dashboard/cron) que soma receita/custo/lucro de
`sale_items` de vendas `concluida` no período (`revenue`, `cost`, `profit`, `sale_count`); vendas
`cancelada` não entram. `financial_summary()` passa a incluir a chave **`products`** com esse resultado,
**sem misturar** com `revenue`/`commissions`/`net` (estrutura de custo de produto — CMV — é diferente da
de comissão de serviço, conforme o plano); consumidores existentes (`/financeiro/gestor` do bot,
`/admin/gestor`, `kernel_ia_finance`, push diário) ignoram a chave nova sem quebrar (Pydantic default
`extra="ignore"` ao desempacotar `**data`). Os endpoints `/financeiro`/`/financeiro/mensal` (dashboard
do dia/mês) não usam `financial_summary()` — calculam receita de serviço inline — então **não** ganharam
o card de produto nesta fase; ficará para quando o dashboard for revisado.

Suíte **705 pass / 2 ambientais / 0 regressões** (+2 em `tests/test_product_sales_summary.py`: soma só
vendas concluídas, `financial_summary` inclui `products` sem afetar `revenue`). Validado end-to-end no
browser (dev local): agendamento real do Taylor → "Concluir atendimento" → "+ Produtos" → carrinho com
Refrigerante lata → confirmar → `Sale` criada com `appointment_id`/`client_id` corretos, estoque baixou
(50→49), `Payment`/`AppointmentItem` do atendimento intactos (R$ 50,00 de receita de serviço, sem
mistura com o R$ 6,00 do produto). **Achado de sessão (não é bug, documentado para não repetir a
investigação):** a mesma imprecisão de automação por coordenada/timing do achado do D-90 (Select+Dialog)
apareceu de novo neste fluxo — cliques via clique-de-coordenada ou mesmo via `ref` do accessibility tree
por vezes reabrem/fecham o popup do `Select` sem selecionar, e o `textContent` lido via JS logo após um
clique pode não refletir ainda o estado renderizado (a leitura por `getElementById(...).textContent`
mostrava "Selecione" um instante depois de o screenshot já mostrar a opção certa escolhida). A forma
confiável de validar por automação foi disparar `element.click()` via `javascript_tool` direto no
elemento `[role="option"]` já aberto, com uma pequena espera antes de ler o resultado — não há ação
de código a tomar. **✅ DEPLOYADO em prod 2026-08-04** junto com a Fase 3 (mesmo deploy, sem migration
própria) — validação em prod restrita a `/health`/rotas 401 (sem credencial real de produção à mão para
smoke test autenticado); fluxo completo ("+ Produtos" na comanda) já validado end-to-end em dev local
antes do deploy.

**Produtos/Estoque/Vendas — Fase 5: fornecedores e compras (D-93, 2026-08-04 — ✅ DEPLOYADO em
prod 2026-08-04):** `suppliers`/`purchase_orders`/`purchase_order_items` (migration `0054`, molde
`sales`/0053 — RLS+FORCE+GRANT SELECT/INSERT/UPDATE, sem DELETE — arquivar fornecedor via `active`,
cancelar pedido via `status`, nunca apagar linha). `PurchaseOrder` nasce `rascunho` →
`PATCH /compras/{id}/enviar` marca `enviado` → `POST /compras/{id}/receber` lança
`stock_movements` tipo `entrada_compra` (já existia no enum desde a 0052) via
`apply_stock_movement` **por item recebido** e recalcula `ProductVariant.cost_avg` por média
ponderada (`(stock_atual×cost_atual + qty_recebida×unit_cost) / (stock_atual+qty_recebida)`) —
validado round-trip: 1º recebimento de 5un a R$10 → `cost_avg=10`; 2º de 5un a R$20 →
`cost_avg=15`. Recebimento é **parcial-capaz**: `qty_received` acumula por item, `status` deriva do
total recebido × total pedido (`recebido_parcial`/`recebido`, `received_at` carimbado só quando
100%); pedir mais do que o restante → 422. Cancelar só antes de qualquer recebimento (`rascunho`/
`enviado`) → 409 depois. **Correção durante a implementação:** `criar_pedido` bloqueia variação de
produto sem `tracks_stock` (422) — sem essa checagem seria possível comprar/receber estoque de um
produto que declara não ter controle de estoque, quebrando a garantia da Fase 2
(`products.tracks_stock=false` nunca gera `stock_movements`). Permissões novas
`suppliers.{view,manage}`/`purchases.{view,manage}` (bloco `_OPERATIONS` → recepção só `view`;
`manage` só owner/manager via `_ALL`/`_MANAGER`, ela vende/opera estoque mas não fecha compra com
fornecedor). Router `app/api/fornecedores.py` (CRUD fornecedores + ciclo de vida do pedido),
auditado (`suppliers.supplier.*`/`purchases.order.*`). Frontend: `/admin/fornecedores`
(`components/fornecedores/`: `fornecedor-panel.tsx` molde `categoria-panel.tsx`,
`pedido-form-dialog.tsx` com carrinho multi-item [produto→variação→qtd+custo unit., molde
`produto-picker.tsx`], `pedido-receber-dialog.tsx` com quantidade por item pré-preenchida com o
restante, `pedidos-table.tsx` com badge de status + ações Enviar/Receber/Cancelar gated por
`purchases.manage`) + `hooks/use-fornecedores.ts` + item "Fornecedores" na sidebar (grupo GESTÃO,
`perm="suppliers.view"`). Suíte **719 pass / 2 ambientais / 0 regressões** (+14 em
`tests/test_fornecedores.py`: RLS, RBAC recepção-vê-mas-não-gerencia, ciclo rascunho→enviado→
recebido, custo médio ponderado, recebimento parcial completa em 2 chamadas, receber além do
pedido→422, cancelar após recebimento→409, produto sem controle de estoque→422). Validado
end-to-end no browser (dev local): criar fornecedor → criar pedido (carrinho com Refrigerante
lata, 10un a R$2,50) → Enviar → Receber (recebimento total) → `stock_movements` mostra "Entrada
(compra) +10" ligada ao pedido, saldo do produto sobe corretamente. **Achado de sessão (mesma
causa do D-90/D-91, não é bug — documentado para não repetir a investigação):** clique por
coordenada de pixel no `Select` de dentro de um `Dialog` volta a resetar visualmente a seleção de
um campo irmão ao interagir com outro; usar `element.click()` via `javascript_tool` direto no
`[role="option"]` (com uma pequena espera) é a forma confiável de validar por automação — o valor
real do estado React nunca se perdeu, só a leitura/clique por coordenada é que é não-confiável
sob a ferramenta de automação. **✅ DEPLOYADO em prod 2026-08-04** (backend `87fb7fe` + frontend
`1eb6721`; backup `~/predeploy_d93_fornecedores_20260804_101940.sql` na VM; migration `0054`
aplicada, head `0054`; `sync_authz_catalog.py` rodado — catálogo com 72 permissões/9 papéis/298
vínculos, igual ao dev local). **Achado do próprio deploy (corrigido na hora, não é dívida):**
`scripts/sync_authz_catalog.py` lê `ADMIN_DATABASE_URL` (não `DATABASE_URL`) e essa variável
**não está** no `.env` da VM (dívida já documentada desde o D-46) — sem ela o script cai no
fallback `localhost`, que não existe dentro do container, e falha com "connection refused". Migration
`0054` e o sync rodados via container avulso do backend montando o repo do host, como superuser
`postgres`, na rede `barbearia_network` (molde D-60/D-67/D-89), passando `ADMIN_DATABASE_URL`
explícito por `-e` no `docker run`. Rebuild `backend`+`frontend` só com
`-f docker-compose.app.yml` (nunca combinar com `docker-compose.yml`, lição do D-89). Validado:
5 containers healthy, `/health` 200, `/fornecedores`/`/compras` 401 sem token (existiam, protegidos),
`app.`/apex 200 por HTTPS, `api./docs` 404 (V12 intacto), `/auth/login` responde 401 a senha errada
(rota viva), logs do backend sem erro.

**Produtos/Estoque/Vendas — Fase 6: inventário/contagem física (D-94, 2026-08-04 — ✅ DEPLOYADO em prod
2026-08-04, migration `0055` aplicada, head `0055`):** `inventory_counts`/`inventory_count_items` (migration `0055`, molde `suppliers`/0054 —
RLS+FORCE+GRANT SELECT/INSERT/UPDATE, sem DELETE — finalizar via `status`, nunca apagar linha). Abrir
uma contagem (`POST /estoque/inventarios`) congela `stock_qty` corrente de toda variação
rastreada/ativa em `expected_qty` (sem filtro de categoria/produto nesta fase — cobre o cardápio
inteiro). A Raquel informa `counted_qty` por item (`PATCH .../itens/{item_id}`, aceita zero, rejeita
negativo); finalizar (`POST .../finalizar`) gera `stock_movements` tipo `inventario` **só para os itens
divergentes** (`qty_delta = counted_qty - expected_qty`) via `apply_stock_movement` — itens nunca
contados (`counted_qty=null`) são ignorados, sem gerar movimentação nem zerar saldo. Toda escrita de
saldo passa por `app/services/inventory.py::finalize_inventory_count` (nunca escreve `stock_qty`
diretamente). Permissão nova `inventory.count.manage` (bloco `_OPERATIONS` → owner/manager/reception,
igual a `inventory.manage`; ausente do papel barbeiro). Router: endpoints novos em `app/api/estoque.py`
(mesmo arquivo da Fase 2 — inventário é parte do domínio Estoque). Frontend:
`components/estoque/inventario-panel.tsx` (lista de contagens + botão "Nova contagem") +
`inventario-dialog.tsx` (itens com input de contagem, auto-salva no blur, botão "Finalizar") em
`/admin/estoque`. Suíte **+15 em `tests/test_inventario.py`** (RLS, RBAC, congelamento de
`expected_qty`, finalizar sem divergência não gera movimentação, finalizar com divergência gera
`inventario` com o delta certo, item sem contagem é ignorado, PATCH/finalizar após finalizado→409,
finalizar 2×→409). `tsc`/`eslint` limpos.

**Produtos/Estoque/Vendas — Fase 7: relatórios avançados (D-94, 2026-08-04 — ✅ DEPLOYADO em prod
2026-08-04, sem migration):** duas funções novas em `app/services/management.py` (mesmo molde das
demais — `async (db, date_from, date_to)`, reusáveis por bot/dashboard/cron, D-52).
`top_selling_products` soma `qty`/receita de `sale_items` de vendas `concluida` no período, agrupado
por variação, ordenado por quantidade (exposto em `GET /vendas/produtos-mais-vendidos`, gated por
`sales.view`). `stock_turnover` calcula o giro (unidades vendidas ÷ estoque médio) por variação
**reconstruindo o saldo em cada ponta do período a partir do ledger append-only `stock_movements`**
(nunca lido só de `stock_qty`, que é a foto de agora): saldo no fim do período = saldo atual −
movimentações depois do período; saldo no início = saldo do fim − movimentações durante o período;
`turnover = null` quando o estoque médio é zero (ainda não houve saldo positivo no período). Exposto em
`GET /estoque/giro` (gated por `inventory.view`). Frontend: `components/vendas/
produtos-mais-vendidos-panel.tsx` em `/admin/vendas` e `components/estoque/giro-panel.tsx` em
`/admin/estoque`, ambos com janela fixa de 30 dias (sem seletor de período nesta fase — "polish sobre
métricas básicas já expostas", como o plano original define o escopo). Suíte **+5 em
`tests/test_relatorios_produtos.py`** (soma qty/receita, cálculo de giro com reconstrução do saldo,
variante sem venda no período fica de fora, RBAC recepção vê/barbeiro não vê).

**Produtos/Estoque/Vendas — Fase 8: extensibilidade (kits/combos/promoções/cupons) — só desenho,
NÃO implementado, por decisão do plano original.** Documentado aqui para quando entrar em escopo real:
- **Kit/combo de produtos:** `sale_items` já referencia `variant_id`; um kit futuro é (a) um produto
  próprio cuja venda dispara baixa múltipla resolvida em N movimentações de `stock_movements` (uma por
  componente, todas com `reference_type="sale"`/`reference_id` do kit), ou (b) uma tabela
  `kit_components(kit_variant_id, component_variant_id, qty)` que a rota de venda expande antes de
  chamar `apply_stock_movement` por componente. Nenhuma migration de `sales`/`sale_items` seria
  necessária — o kit é só uma variação especial que participa da baixa de mais de uma linha de
  estoque.
- **Desconto simples:** já cabe sem mudança de schema — `SaleItem.unit_price_charged` já é um
  snapshot livre (Decimal), pode divergir de `ProductVariant.price` no momento da venda (mesmo padrão
  de `AppointmentItem.price_charged`).
- **Cupom:** entraria como tabela nova (`coupons` já existe no billing SaaS — este seria um domínio
  separado, cupom de desconto ao cliente final, não confundir) com FK opcional futura em `sales`
  (`sales.coupon_id`, nullable), aplicado no momento da venda e sem retroagir em vendas passadas.
- **Comissão de barbeiro sobre venda de produto** e **fidelidade por pontos em compra de produto**
  seguem fora de escopo por decisão de negócio pendente (não técnica) — ver a tabela de regras de
  negócio consolidada no plano original (`/Users/apleandro/.claude/plans/
  elabore-um-plano-completo-expressive-lovelace.md`).

Com as Fases 6-8 encerradas (6/7 código, 8 só documentação), o plano completo de Produtos/Estoque/
Vendas está com todas as 8 fases endereçadas. **✅ DEPLOYADO em prod 2026-08-04** (backend `c273d0b` +
frontend `34bd3d4`, molde D-90/D-91/D-93; migration `0055` aplicada via `deploy/update.sh` de ponta a
ponta — primeiro deploy real usando o script corrigido no D-93 — + `sync_authz_catalog.py` rodado à
parte, 73 permissões/9 papéis/302 vínculos; validado `/health` 200, rotas novas 401 sem token,
`app.`/apex 200 por HTTPS). Ver D-94.

**Kernel IA ganha visão de estoque — tool `consultar_estoque` (D-95, 2026-08-05 — ✅ DEPLOYADO em
prod 2026-08-05, backend `8eb66df` + frontend `553f908`, sem migration):** o Kernel IA (D-57/D-58) nunca tinha visibilidade sobre o módulo de Produtos/
Estoque/Vendas (Fases 1-7, D-90/D-94); esta decisão fecha essa lacuna, no mesmo molde
anti-alucinação do `consultar_financas`. **Só consulta/leitura** — sem lançar ajuste/perda/entrada
via chat nesta fase (decisão de escopo, reduz risco de mutação por linguagem natural).
**RBAC: `FULL_ACCESS`** (owner/manager/**recepção**) — diferente do financeiro, que é
`MANAGER_ACCESS`-only: estoque é dado operacional que a Raquel já opera na UI normal
(`inventory.view`/`inventory.manage`), não dado financeiro sensível; barbeiro continua fora.
Novo módulo `app/services/kernel_ia_stock.py` (par de `kernel_ia_finance.py`): `TOPICS =
("alertas", "niveis", "giro")` — `alertas` reaproveita `inventory.low_stock_alerts`; `niveis` é
nova função `management.stock_overview(db)` (total de variantes ativas rastreadas, quantas no
mínimo/abaixo, quantas zeradas, valor total em estoque a custo médio); `giro` reaproveita
`management.stock_turnover`. Deixado fora de propósito: `movimentacoes` (lista granular do
ledger, sem pergunta natural de chat óbvia — melhor resolvida navegando para `/admin/estoque`).
`kernel_ia.py` ganha o branch `consultar_estoque` em `_tools_for_role`/`_dispatch`/`answer()`
(checagem RBAC redundante no dispatch, mesmo padrão de defesa em profundidade do financeiro) e o
`action="stock_answer"` novo no contrato do endpoint. **Sem insight de LLM nesta fase** (dado
operacional, sem playbook curado ainda — fácil adicionar depois reaproveitando
`kernel_ia_finance.guard_insight`). Frontend: nenhuma mudança funcional (`kernel-ia-launcher.tsx`
já trata qualquer `action` desconhecido mostrando a mensagem), só o union type de `action` em
`use-kernel-ia.ts` ganhou `"stock_answer"` por clareza. Suíte **748 pass / 2 ambientais / 0
regressões** (+15 testes: `tests/test_kernel_ia_stock.py` formatação pura, extensão de
`tests/test_kernel_ia.py` para RBAC/dispatch — recepção TEM `consultar_estoque` diferente do
financeiro, barbeiro não tem —, `tests/test_relatorios_produtos.py` para `stock_overview`). **✅ DEPLOYADO em prod 2026-08-05**
(molde D-93/D-94: `git pull` do backend + `git -C barbearia-frontend pull` [submódulo, deploy key
própria] + rebuild `backend`+`frontend` via `docker compose -f docker-compose.app.yml up -d
--build`; validado ambos `healthy`, `/health` 200, `/kernel-ia/query` e `/estoque/alertas` 401 sem
token, `app.`/apex 200 por HTTPS, `/docs` 404 intacto, sem erros nos logs).

**Site público — seção "Não é apenas um serviço. É uma experiência." (2026-08-13 — ✅ DEPLOYADO em
prod, sem migration):** novo componente `barbearia-public/components/ritual.tsx` (server component,
zero JS) inserido em `app/page.tsx` entre "Serviços" e "Nossa casa" — 6 cards (Consulta/Corte/Textura/
Cor/Finalização/Cuidado) com foto still-life/macro editorial em `public/ritual/*.webp`, geradas
propositalmente **sem rosto humano nem cena de atendimento "documentada"** (evita fingir ser registro
real do salão), na paleta ouro/grafite do D-82. Reaproveita só tokens/padrões já existentes
(`bg-superficie`, `border-borda-sutil`, `--sombra-1`, `font-display`) — nenhuma mudança em `globals.css`
nem no backend. Deploy no molde D-79/D-80/D-82: `git pull --ff-only` + `docker compose -f
docker-compose.app.yml up -d --build public` (backend recriado junto). **Rollback:** `git revert
9031a37` (ou `git reset --hard 56067d8`) + repetir o rebuild — sem migration, reverter é seguro.
**Complemento (mesmo dia, commit `9f4d279`):** régua de estatísticas do `Hero` (`hero.tsx`) portou o
acabamento visual do mesmo redesign — números passam de `font-display` (serifada) para sans-serif
`font-semibold` (mais legível como dado), e a estatística "Nota Google" ganha 5 estrelas douradas ao
lado do valor (`estrelas: boolean` novo no array `numeros`). Só CSS/JSX, sem mudança de dado/API.
Rollback: `git revert 9f4d279` + rebuild `public`.

**Placeholders ("Em breve") no frontend:** `campanhas`.
(`empresa` implementada — D-45: cadastro, endereço/horário e plano via `/empresa`.)

**Pendente (visão do produto):** Caixa · Consumo de produtos no atendimento · Estoque/Produtos ·
Renovação **automática** de mensalidade (a manual já existe — D-44) · Dashboard executivo
(comercial, financeiro, operacional, **leads fora do horário comercial / faturamento gerado pela IA**) ·
Multi-tenant real no frontend · Arquitetura de múltiplos agentes.

---

## 7. Pendências técnicas / riscos (backlog priorizado)

Detalhe completo (com `arquivo:linha`) na auditoria:
`/Users/apleandro/.claude/plans/partitioned-greeting-stearns.md`.

**🔴 Crítico:** `credentials.json` no histórico git (rotacionar credencial OpenAI/n8n + limpar histórico) ·
portas Postgres/n8n/Evolution abertas ao mundo + sem HTTPS · SSE single-process (não escala) ·
~~multi-tenant só de fachada no frontend (`NEXT_PUBLIC_ORG_ID` fixo em build)~~ (✅ D-54 DEPLOYADO em prod 2026-06-30,
DNS ativo desde D-64 2026-07-05: resolução por subdomínio (`taylor.taylorethedy.com`, confirmado em prod)
e instância WhatsApp (bot); falta só n8n `X-Instance`) · VM única sem HA.

**🟠 Alto:** ~~webhook secret opcional~~ (✅ D-76, 2026-07-14, DEPLOYADO em prod: `WA_WEBHOOK_SECRET` configurado
nos dois lados, testado ao vivo) · `except Exception` mudos (✅ D-76 parcial: `create_coupon` corrigido; demais
já eram design deliberado, não mascaramento) · ~~SQL via f-string em advisory lock~~ (✅ D-76, commitado: bind
parameter nos 3 pontos) · pool DB no default / sem PgBouncer / sem fila de workers · React Query não usado ·
páginas-monolito (`crm/page.tsx` 1389 linhas) · cron n8n em série p/ todas as orgs ·
~~repo frontend com remote morto~~ (✅ D-08, 2026-06-29: remote restaurado + submódulo registrado)
· ~~JWT sem revogação/refresh~~ (✅ D-68, 2026-07-09, DEPLOYADO em prod: refresh rotativo + `sessions` + Redis
para rate-limit/lockout/tickets — Redis passou a existir no stack, mas só para esse uso efêmero, não como cache
geral).

**🟡 Médio:** transações inconsistentes · `Payment` desacoplado de `Appointment` · dados hardcoded no
frontend · next-auth beta / sem refresh token · acessibilidade fraca · sem i18n · docs dispersas.

---

**Notificações push no celular — profissionais e clientes (D-96, 2026-08-14 — ✅ DEPLOYADO em prod
2026-08-14, migration `0056` aplicada, head `0056`; plano em
`/Users/apleandro/.claude/plans/lazy-squishing-minsky.md`):** Web Push padrão
(VAPID, `pywebpush`), sem Firebase/FCM — funciona em Android (Chrome) e iOS 16.4+ (exige o app
**adicionado à Tela de Início**, limitação da Apple). Migration `0056` (molde `sales`/0053 —
RLS+FORCE, GRANT SELECT/INSERT/UPDATE, sem DELETE): `push_subscriptions` (uma subscrição de
navegador por dispositivo, ligada a `user_id` OU `client_id`, nunca os dois — CHECK) +
`push_notification_log` (molde de `MessageLog`, mas genérico para os dois tipos de assinante;
idempotência atômica por `idempotency_key`, canal independente do WhatsApp). `app/services/push.py`:
`dispatch()` reserva a key e envia a todos os dispositivos ativos do assinante (revoga subscrição
morta em 404/410); `notify_booking_confirmation` dispara a confirmação **imediata** do cliente ao
agendar pelo site público (`BackgroundTasks`, molde `calendar_sync.push_appointment`);
`run_near_reminders` cobre o lembrete "de última hora" (30min por padrão,
`push_client_near_lead_minutes`/`push_professional_lead_minutes`) tanto do cliente quanto do
profissional (via `UserUnit.barber_id`), numa janela de cron bem mais fina que o lembrete de 24h.
`app/services/reminders.py::run()` (o cron de 24h existente) ganhou um segundo branch de push em
paralelo ao WhatsApp — canais independentes, idempotência própria. Endpoints:
`POST/DELETE /notificacoes/push/subscription` (equipe, JWT, self-service — sem permissão nova no
catálogo) em `app/api/push.py`; `POST/DELETE /public/{subdomain}/push/subscription` (cliente final,
cookie de sessão) em `app/api/public.py`; `POST /internal/push/near-reminders/run` (cron novo do
n8n a cada ~10min, `X-Bot-Token`) — **✅ cron criado e publicado no n8n** ("BarbeariaPro Cron - Push
Lembrete Ultima Hora", clonado do workflow de 24h existente, mesma expressão de token
`{{ $env.BOT_API_KEY }}`; `*/10 * * * *`; testado manualmente via "Execute workflow" →
`{sent:0, skipped:0, total_targets:0}`, 200 OK). **Frontend:** `barbearia-public/` (já PWA) ganhou os listeners de
`push`/`notificationclick` no `sw.js` (`SW_VERSION=v5-push-2026-08-14`) + `lib/push.ts` +
`components/ativar-notificacoes.tsx` (tela de sucesso do agendamento + "meus agendamentos″).
`barbearia-frontend/` (painel da equipe) **virou PWA pela primeira vez** — `manifest.webmanifest` +
`sw.js` novos, reaproveitando os mesmos ícones "T" (`icon-192.png`/`icon-512.png`/
`apple-touch-icon.png`, copiados do site público, D-82) — + `lib/push.ts` + `hooks/
use-push-subscription.ts` + banner "Ativar notificações" no layout do barbeiro (`app/barbeiro/
layout.tsx`, área que não usa o `AdminShell`, D-87). Env nova nos dois frontends:
`NEXT_PUBLIC_VAPID_PUBLIC_KEY`. Suíte **+7 em `tests/test_push.py`** (subscrição self-service,
confirmação imediata dispara o claim, idempotência não duplica, revogação em 404/410 simulado, RLS
entre orgs); build+tsc limpos nos dois frontends.
> **Achado do próprio deploy (corrigido antes de terminar, não é dívida):** o `proxy.ts` (middleware
> de auth do painel) redirecionava `/sw.js`/`/manifest.webmanifest`/ícones para `/login` quando
> deslogado — o navegador recebia HTML em vez de JS/JSON e o registro do service worker falhava em
> silêncio (`RegisterSW` roda em toda página, inclusive `/login`). Fix: matcher do `proxy.ts` exclui
> esses paths (commit `b6dbc01`), redeployado antes do smoke test final.
**✅ DEPLOYADO em prod 2026-08-14** (backend `1f73716`→`700c8e2` + frontend `677bd24`→`b6dbc01`;
migration `0056` rodada via `deploy/update.sh` de ponta a ponta; backup `~/predeploy_d96_push_
20260814_174431.sql`): chaves VAPID geradas (`py_vapid`) e provisionadas no `.env` da VM; build args
`NEXT_PUBLIC_VAPID_PUBLIC_KEY` adicionados aos 2 Dockerfiles + `docker-compose.app.yml` (reaproveita
`VAPID_PUBLIC_KEY` do backend, sem variável duplicada); cron `/internal/push/near-reminders/run`
criado e publicado no n8n. Validado: 5 containers healthy, `/health` 200, `/notificacoes/push/
subscription` 401 sem token, `sw.js`/`manifest.webmanifest`/ícones 200 sem login em
`app.taylorethedy.com`, `/admin/agenda` ainda protegido (307), execução manual do cron novo retornou
200 com o contrato esperado. **Falta só:** validação visual num celular real (Android + iOS
instalado) — sem dispositivo físico disponível nesta sessão.

---

## 8. Roadmap de execução (decidido)

- **Fase 0 — Memória técnica:** este `CLAUDE.md`. ✅
- **Fase 1 — Segurança (prioridade nº 1):**
  - 1.1 ✅ *(2026-06-26)* — removido `print` de debug do webhook; comparação tempo-constante
    (`secrets_match`) para `X-Bot-Token` e `X-Webhook-Secret`. Sem regressão (205 pass; 3 falhas
    pré-existentes/ambientais).
  - 1.2 — rotacionar credencial n8n/OpenAI exposta (`credentials.json` no histórico git público).
    `SECRET_KEY` da VM **verificado 2026-06-26: forte** (64 chars, ~hex 256 bits) — o placeholder
    estava só no `.env` local, não em produção. **Não rotacionar** (sem ganho; derruba sessões).
  - 1.3 — limpar histórico git (`git filter-repo`) + force-push coordenado.
  - 1.4 ⏳ parcial *(2026-06-26)* — firewall GCP: removidas `allow-n8n` (5678) e `allow-evolution`
    (8080); 5432 já estava fechada. Bot não afetado (fluxo interno). n8n/Evolution Manager agora só por
    SSH tunnel (ver D-40). **Falta:** domínio + HTTPS (mover 8000/3000 para trás do nginx); tornar
    webhook secret obrigatório (provisionar nos 2 lados).
- **Fase 2 — Fundação de escala:** SSE → Postgres LISTEN/NOTIFY (ou Redis); pool/PgBouncer; `org_id`
  dinâmico no frontend; backups automatizados; mover frontend p/ remote vivo.
- **Fase 3 — Qualidade:** React Query; extrair componentes reutilizáveis; quebrar páginas-monolito;
  padronizar transações; substituir `except Exception` mudos; parametrizar SQL.
- **Fase 4+ — Produto:** Caixa, Consumo/Estoque, Pacotes/Assinaturas, Fidelização, Dashboard executivo,
  arquitetura de agentes — cada item entra com plano próprio e aprovação.

---

## 9. Como rodar / testar
- **Testes (backend):** `PROJECT_CONTEXT.md §14`
  ```bash
  docker start barbeariapro-staging-postgres
  set -a; . ./.env.staging; set +a
  export SEED_ORG_ID=1
  .venv/bin/python -m pytest tests/ -q
  ```
  Baseline atual (2026-07-09, pós D-70): **564 pass / 2 fail (ambientais) / 2 skip**. As 2 falhas (config workflow
  n8n `bypass_hours`, e2e link barbeiro↔serviço) são de seed/ambiente, não de código.
- **Deploy:** procedimentos backend (git pull + compose) e frontend (scp + build) em `PROJECT_CONTEXT.md §2`.

---

> **Ao concluir qualquer tarefa:** rodar testes, validar fluxos relacionados, **atualizar o graphify
> (`graphify-out/`) automaticamente** (§0), atualizar este arquivo e `DECISIONS.md`/`CURRENT_SPRINT.md`
> quando aplicável, e informar claramente o que mudou.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
