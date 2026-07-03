# Arquitetura — Painel SuperAdmin + Billing

> Consolidado da análise completa (M1, 2026-07-03) por três frentes: backend core,
> billing existente e frontends. Fontes primárias: `CLAUDE.md`, `DECISIONS.md`
> (D-54/D-55/D-56/D-60), código. Decisões novas: `decisions.md` (SA-D01…).

## 1. Visão geral do ecossistema

```
barbearia-frontend (tenant, :3000)      barbearia-superadmin (:3100)
        │ next-auth v5 (token org)              │ next-auth v5 (token typ=platform)
        ▼                                       ▼
              FastAPI backend (:8000)  /Users/apleandro/dev/barbeariapro
                    │  RLS por app.current_org_id (única barreira)
                    ▼
              PostgreSQL 16 (role barber_app = NOBYPASSRLS)
```

- **Monorepo** `barbeariapro` = backend + docs + submódulos dos dois frontends.
- **Superadmin**: clone de trabalho em `/Users/apleandro/dev/barbearia-superadmin` (= submódulo `C2`).
- **Tenant**: submódulo `barbeariapro/barbearia-frontend` (branch `feat/multi-tenant-org-id`, tema claro/escuro)
  + worktree `barbearia-frontend-kernelia` (branch `feat/kernel-ia-launcher`, dark fixo). Mesmo repo git.
- Prod: VM GCP única (`34.95.199.134`), nginx no host, compose infra + compose app.
  Serviço `superadmin` pronto sob profile `superadmin` (bloqueado por domínio — B-01).

## 2. Backend (o que o painel consome e estende)

- **Stack**: Python 3.12 · FastAPI · SQLAlchemy 2 async (psycopg3) · Alembic (head `0027`) · Pydantic v2 · JWT HS256.
- **Auth de plataforma (D-55)**: `platform_admins` (sem RLS, sem GRANT ao app) + `create_platform_token` →
  claims `{sub, typ:"platform"}` SEM `org`. Isolamento bilateral com token de tenant (que tem `org`, sem `typ`).
  Guard `require_platform_admin` revalida o admin a cada request via SECURITY DEFINER.
- **Regra de ouro cross-tenant**: endpoint de plataforma NUNCA seta `app.current_org_id` na própria sessão.
  Leitura → funções SECURITY DEFINER (`app/services/platform.py`); escrita escopada → sessão helper isolada
  com `set_current_org` (ex.: `patch_org`, `_set_org_deleted` em `app/api/platform.py`).
- **RBAC de tenant**: `owner > manager > reception > barber` (`app/core/rbac.py`), guards imperativos
  (`require_manager_access(role)`) após `resolve_current_role`.
- **Como estender** (molde completo no relatório do arquiteto, resumo):
  model em `models/*.py` + registro em `models/__init__.py` → migration manual `0028+` com bloco RLS
  (molde `0023_client_debts`) e CHECKs espelhados (D-60) → schemas Pydantic INLINE no router →
  router registrado em `app/main.py` → testes `tests/test_*_{unit,integration}.py` (fixtures do `conftest`;
  testes de plataforma exigem `ADMIN_DATABASE_URL`, skip sem ela).
- **Env**: pydantic-settings (`app/core/config.py`); duas conexões — `DATABASE_URL` (barber_app) e
  `ADMIN_DATABASE_URL` (role dona, só migrations/seeds). Novas vars de billing entram no `Settings`.
- **Testes**: `docker start barbeariapro-staging-postgres` + `.env.staging` + `SEED_ORG_ID=1` +
  `.venv/bin/python -m pytest tests/ -q`. Baseline 408 pass / 2 ambientais.

## 3. Billing — estado atual vs. alvo

**Existe** (migration 0001/0021): `plans` (catálogo global: `price_month`, `max_units`, `max_barbers`,
`features` jsonb nunca lido) · `subscriptions` (org, plan, enum `trial|active|past_due|canceled`,
`current_period_start/end`, `canceled_at`) · trial de 365d hardcoded no onboarding · status exibido é
**derivado** (`suspended` = `organizations.deleted_at`; `sem_assinatura` = sem linha) ·
`saas_mrr` = Σ `price_month` das ativas · `tenants_membership_mrr` = mensalidades dos clientes finais (loop O(N)).

**Não existe**: gateway (zero SDK), invoices/pagamentos SaaS, tentativas/dunning, cupons/créditos,
transição automática de status (nada consome `current_period_end`), enforcement de limites/features,
webhook de pagamento, audit log dedicado.

**Moldes internos a reaproveitar**: idempotência+retry de `MessageLog` (`idempotency_key` UNIQUE,
`attempt_count`, `next_retry_at`, índice parcial) · ledger append-only (`loyalty_point_ledger`) ·
webhooks de mensageria (`wa_webhook.py`, `chatwoot.py`) · SECURITY DEFINER da 0021.

**Alvo (SA-D01…SA-D08, resumo)**: domínio local dono dos entitlements; Stripe dono do dinheiro;
`BillingProvider` (ABC) com `StripeBillingProvider` (único import de stripe) + `MockBillingProvider`
(default sem chave); tabelas novas `plan_prices`, `plan_features`, `plan_limits`, `feature_flags`,
`billing_customers`, `invoices`, `billing_payments` (nome distinto do `payments` do cliente final!),
`payment_attempts`, `coupons`, `discounts`, `billing_credits`, `usage_metrics`, `billing_events`,
`webhook_events`, `platform_audit_log`; Checkout `mode=subscription` + Customer Portal + Prices;
dunning da Stripe (Smart Retries) apenas REGISTRADO localmente; lifecycle job p/ provider manual;
entitlements em 3 níveis (`full`/`restricted`/`blocked`) com rollout fail-open→fail-closed.

## 4. Frontend superadmin (este painel)

- Next 16 App Router · TS strict · Tailwind v4 · next-auth v5 (Credentials → `/platform/auth/login`) ·
  React Query · axios. Porta 3100. Guard de sessão em `proxy.ts`.
- **Padrão de página**: `"use client"` → `usePlatform()` → `useQuery`/`useMutation` com
  `invalidateQueries` → `<Shell><PageHeader/>…` → tabela hand-rolled em `<Card>`.
  Tipos + client em `lib/platform.ts` espelhando `app/api/platform.py`.
- **Tema**: dark fixo, brand amber `#f59e0b`, tokens shadcn-style no `:root` (`app/globals.css`).
- **Dívidas herdadas do scaffold** (fechadas no M2): sem primitivos dialog/input/select/tooltip
  (modais inline, inputs crus), sem `patterns/*` (estados ad-hoc), sem fonte carregada, sem
  tokens de chart/motion, sem AGENTS.md.
- **Fonte de componentes**: copiar do tenant (`barbearia-frontend`) — `components/patterns/*`
  (AsyncState/Skeleton/EmptyState/ErrorState/Spinner), primitivos base-ui (`dialog`, `input`,
  `select`, `tooltip`, `avatar`), tokens (`--chart-1..5: #f59e0b #22c55e #3b82f6 #a855f7 #06b6d4`,
  motion, z-index, Inter). Manter de B: `platformClient` tipado, `StatusBadge`, `brl`/`shortDate`.

## 5. Frontend tenant (onde o M8 toca)

- "Assinaturas" na sidebar do tenant = mensalidades que a BARBEARIA vende aos clientes dela
  (`/admin/assinaturas`, API `/memberships/*`). **Não confundir.**
- Assinatura SaaS do tenant → visão read-only em `/admin/empresa` (`components/empresa/plano-card.tsx`).
  **Lar do "Minha Assinatura/upgrade/portal" (M8) = estender `/admin/empresa`.**
- Trabalhar na branch/checkout mais recente (`barbeariapro/barbearia-frontend`, `feat/multi-tenant-org-id`).

## 6. Segurança (aplicada à missão)

- Tokens de plataforma expiram (maxAge 8h no painel); impersonação (M10) emitirá token de TENANT
  curto (30 min) com claims `imp_by`/`imp_reason`, sempre auditado em `platform_audit_log`.
- Webhook Stripe: assinatura verificada no provider (`STRIPE_WEBHOOK_SECRET`); persistência bruta
  idempotente antes de processar; replay controlado.
- Segredos só via env/settings; chave recomendada: restricted key (B-02); nunca logar chave/payload sensível.
- Tabelas de plataforma sem GRANT direto ao `barber_app` (molde `platform_admins`).
