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
> - `/Users/apleandro/.claude/plans/partitioned-greeting-stearns.md` — auditoria completa + plano de evolução (origem deste arquivo).

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
  - **Arquitetura de domínios (decisão do dono, 2026-07-06):** `taylorethedy.com` (apex) = **página do cliente
    final** da org 1 (a fazer); `taylor.taylorethedy.com` será renomeado para **`org.taylorethedy.com`** = portal
    de login de funcionários/donos/gerentes. A regex de CORS já cobre ambos — o rename não toca o backend.
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
  `POST /kernel-ia/query` — o LLM (OpenAI `gpt-4o-mini`, `OPENAI_API_KEY`) só escolhe uma rota de
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
> ⚠️ **Bloqueio conhecido em prod (2026-07-02): `OPENAI_API_KEY` da VM está inválida/expirada**
> (401 da OpenAI). Kernel IA inteiro (D-57 navegação + D-58 finanças) degrada com graça
> (`action=config`, "chave inválida ou expirada" — sem 500), mas **ninguém consegue usar o chat
> até a chave ser rotacionada** em `/opt/barbeariapro/.env`. Pré-existente, não causado pelo D-58 —
> só ficou visível agora porque foi a 1ª vez que o Kernel IA (FAB do frontend) foi de fato
> deployado em prod. Validação manual "LLM real" do D-58 **ainda pendente** por causa disso.

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

**Segurança / Governança — Visibilidade do site público (D-73, Fase 6 — ✅ COMMITADO 2026-07-09, não deployado
em prod):**
`client_visibility_settings` (migration `0041`, 1:1 por org, RLS+FORCE) guarda a CONFIGURAÇÃO de serviços/
profissionais/horários/avaliações/promoções/banner/dados públicos exibidos — o site público em si **ainda não
existe** no produto (decisão combinada: construir só a configuração, sem endpoint público de leitura, que fica
para quando o site entrar no roadmap). `GET/PUT /admin/security/site-visibility` reaproveita
`security.site_visibility.manage` (já no catálogo desde o D-67). Frontend `/admin/seguranca/visibilidade` +
item na sidebar. Suíte 582 pass / 2 ambientais / 0 regressões. Detalhes em DECISIONS.md D-73.

**Placeholders ("Em breve") no frontend:** `campanhas`, `usuarios`.
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

**🟠 Alto:** webhook secret opcional (tornar obrigatório após provisionar nos dois lados) · `except
Exception` mudos · SQL via f-string em advisory lock · pool DB no default / sem PgBouncer / sem
fila de workers · React Query não usado · páginas-monolito (`crm/page.tsx` 1389 linhas) ·
cron n8n em série p/ todas as orgs · ~~repo frontend com remote morto~~ (✅ D-08, 2026-06-29: remote restaurado + submódulo registrado)
· ~~JWT sem revogação/refresh~~ (✅ D-68, 2026-07-09, DEPLOYADO em prod: refresh rotativo + `sessions` + Redis
para rate-limit/lockout/tickets — Redis passou a existir no stack, mas só para esse uso efêmero, não como cache
geral).

**🟡 Médio:** transações inconsistentes · `Payment` desacoplado de `Appointment` · dados hardcoded no
frontend · next-auth beta / sem refresh token · acessibilidade fraca · sem i18n · docs dispersas.

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

> **Ao concluir qualquer tarefa:** rodar testes, validar fluxos relacionados, atualizar este arquivo e
> `DECISIONS.md`/`CURRENT_SPRINT.md` quando aplicável, e informar claramente o que mudou.
