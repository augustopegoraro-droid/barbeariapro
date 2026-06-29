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
- `barbearia-frontend/` — **repo git aninhado separado** (ver §7, remote morto).

---

## 3. Regras de negócio e fluxos atuais

### Autenticação / multi-tenant
- Login: `POST /auth/login {organization_id, email, password}` → `set_current_org()` **antes** de
  consultar (RLS) → bcrypt → JWT `{sub:user_id, org:org_id, exp}`.
- `get_tenant_db()` (`app/deps.py`) decodifica Bearer, abre transação e faz
  `SELECT set_config('app.current_org_id', :org, true)` (parametrizado, **local à transação** — não
  vaza no pool). **RLS é a única barreira multi-tenant.**
- RBAC por unidade: `owner > manager > reception > barber` (`app/core/rbac.py`).
- Bot: header `X-Bot-Token` validado contra `settings.bot_api_key`. Webhook Evolution:
  `X-Webhook-Secret` (hoje opcional). Comparações de segredo são **tempo-constante** via
  `app.core.security.secrets_match()`.

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
multi-tenant só de fachada no frontend (`NEXT_PUBLIC_ORG_ID` fixo em build) · VM única sem HA.

**🟠 Alto:** webhook secret opcional (tornar obrigatório após provisionar nos dois lados) · `except
Exception` mudos · SQL via f-string em advisory lock · pool DB no default / sem PgBouncer / sem
Redis / sem fila de workers · React Query não usado · páginas-monolito (`crm/page.tsx` 1389 linhas) ·
cron n8n em série p/ todas as orgs · **repo frontend aninhado com remote morto** (`DoctorDCombo/...`).

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
