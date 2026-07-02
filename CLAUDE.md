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
  **Deploy preparado, não ativado:** serviço `superadmin` no `docker-compose.app.yml` sob
  **profile `superadmin`** (não sobe no `up` padrão) + `Dockerfile` + server block
  `admin.taylorethedy.com`→:3100 em `deploy/nginx.conf` + `.env.superadmin.example`.
  Ativação pós-domínio (mesma VM, **não** precisa VM nova): DNS + `up --profile superadmin`
  + certbot.
- **Pendente:** compra do domínio (`admin.taylorethedy.com`) + ativação do deploy acima;
  saúde de bot ao vivo (conectado/restrito) exige Evolution API (hoje só o proxy
  `wa_instance_name`).

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
> appointments,ranking,debts}` (gestor; corpo = CSV bruto, sem multipart; `commit=false` dry-run →
> `commit=true` grava; RLS pela org do token). Parsers aceitam `bytes` ou path.
> **Ranking** (`trinks_ranking.py`): enriquece clientes (preenche email/nascimento faltantes por
> telefone, nunca sobrescreve). **Débitos** (`trinks_debts.py` + migration `0023` `client_debts` +
> API `app/api/debts.py`: `GET /admin/debts`, `/summary`, `POST /{id}/pay|reopen`): contas a receber
> (não cabia em `payments`); casa cliente por nome, `client_id` nullable, idempotente.

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
~~multi-tenant só de fachada no frontend (`NEXT_PUBLIC_ORG_ID` fixo em build)~~ (✅ D-54 DEPLOYADO em prod 2026-06-30:
resolução por subdomínio (login) e instância WhatsApp (bot); falta só DNS de subdomínios + n8n `X-Instance`) · VM única sem HA.

**🟠 Alto:** webhook secret opcional (tornar obrigatório após provisionar nos dois lados) · `except
Exception` mudos · SQL via f-string em advisory lock · pool DB no default / sem PgBouncer / sem
Redis / sem fila de workers · React Query não usado · páginas-monolito (`crm/page.tsx` 1389 linhas) ·
cron n8n em série p/ todas as orgs · ~~repo frontend com remote morto~~ (✅ D-08, 2026-06-29: remote restaurado + submódulo registrado).

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
  Baseline atual: **205 pass / 3 fail (ambientais) / 4 skip**. As 3 falhas (config workflow n8n
  `bypass_hours`, RLS isolation, e2e link barbeiro↔serviço) são de seed/ambiente, não de código.
- **Deploy:** procedimentos backend (git pull + compose) e frontend (scp + build) em `PROJECT_CONTEXT.md §2`.

---

> **Ao concluir qualquer tarefa:** rodar testes, validar fluxos relacionados, atualizar este arquivo e
> `DECISIONS.md`/`CURRENT_SPRINT.md` quando aplicável, e informar claramente o que mudou.
