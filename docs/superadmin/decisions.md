# Decisões — Painel SuperAdmin + Billing

> Registro de decisões da missão (prefixo SA-D). Decisões que afetam o monorepo
> como um todo também ganham entrada em `DECISIONS.md` (raiz) ao serem deployadas.
> Contexto: auditoria completa do billing existente em `architecture.md` §Billing.

---

## SA-D01 · Fonte de verdade: entitlements locais, dinheiro no gateway

O banco local é a fonte de verdade de **entitlements** (plano, features, limites,
status da assinatura); o gateway (Stripe) é a fonte de verdade de **movimentação
financeira** (cobranças, retries, faturas). Sincronização gateway→local via
webhooks + `sync_subscription` (reconciliação ativa). **Nenhuma regra de negócio
vive na Stripe** — ela é executor de cobrança, não decisora.

**Por quê:** troca de gateway (Asaas/MercadoPago futuros) não pode exigir migrar
regra de negócio; e o app precisa decidir acesso mesmo com o gateway fora do ar.

## SA-D02 · Evoluir `plans`/`subscriptions` existentes, nunca recriar

As tabelas `plans` e `subscriptions` (migration 0001) e o molde SECURITY DEFINER
da plataforma (migration 0021) são mantidos e **estendidos aditivamente**:

- `plans` += `slug` (estável p/ código), `stripe_product_id`, `is_active`, `sort_order`, `description`.
- Nova `plan_prices` (plan_id, `cycle` mensal/anual, `amount`, `currency`, `provider_price_id`, `active`) —
  `plans.price_month` permanece como espelho do preço mensal ativo (retrocompat: MRR atual lê dele).
- `subscriptions` += `provider` ('manual' default), `provider_customer_id`, `provider_subscription_id`,
  `cancel_at_period_end`, `trial_end`, `paused_at`, `resumes_at`, `updated_at`.
- Enum `subscription_status` += `paused`, `incomplete` (ADD VALUE, aditivo).
  Mapeamento Stripe→interno documentado em `architecture.md` (ex.: `unpaid`→`past_due`).

**Status derivados continuam derivados** (`suspended` = `organizations.deleted_at`;
`sem_assinatura` = ausência de linha): suspensão administrativa é um **eixo
independente** de inadimplência — o superadmin pode suspender uma org adimplente
e reativar uma inadimplente. `_derive_status` permanece o contrato do frontend.

## SA-D03 · Domínio novo (migrations aditivas, sem tocar nas existentes)

| Tabela | Papel | Observações |
|---|---|---|
| `feature_flags` | registro global de recursos (key, nome, descrição, default) | gerenciável no painel |
| `plan_features` | plano ↔ feature (enabled) | substitui uso do jsonb `plans.features` (mantido por retrocompat, congelado) |
| `plan_limits` | plano ↔ limite numérico (`limit_key`, `value`, NULL = ilimitado) | backfill de `max_units`/`max_barbers`; leitura com fallback ao legado |
| `billing_customers` | org ↔ `provider_customer_id` (UNIQUE por provider) | resolução webhook→org via SECURITY DEFINER (molde 0020) |
| `invoices` | faturas do SaaS (status draft/open/paid/void/uncollectible, período, valores, URLs) | sync por webhook; manuais p/ provider `manual` |
| `billing_payments` | pagamentos do SaaS | **nome distinto** — `payments` já existe e é do cliente final (comanda) |
| `payment_attempts` | tentativas por fatura (nº, erro, `next_retry_at`) | molde `MessageLog`; populado por webhook (Smart Retries é da Stripe — não reimplementar régua) |
| `coupons` / `discounts` | cupons (percent/amount, duração) e aplicação org/assinatura | espelhados no provider quando suportado |
| `billing_credits` | ledger append-only de créditos (+/−), saldo = SUM | molde `loyalty_ledger`; aplicado via customer balance (Stripe) ou fatura (manual) |
| `usage_metrics` | contadores por org/métrica/mês (UPSERT) | p/ enforcement e analytics; **não** é metering de cobrança por uso |
| `billing_events` | log append-only de tudo que muda billing (ator, tipo, payload) | é o "subscription history" e o "billing log" da missão — uma tabela só |
| `webhook_events` | eventos brutos recebidos (UNIQUE `(provider, event_id)`, status, erro, replay) | idempotência + auditoria + reprocesso |
| `platform_audit_log` | auditoria de AÇÕES do superadmin (impersonação, reset senha, suspensão, troca de plano…) | separado de billing_events: escopo plataforma, não billing |

**RLS:** tabelas com `org_id` de leitura do tenant (`invoices`, `billing_payments`,
`billing_credits`, `discounts`) ganham RLS por `app.current_org_id` (tenant lê as
próprias em "Minha Assinatura"). Tabelas de plataforma (`webhook_events`,
`platform_audit_log`, `coupons`, `feature_flags`, catálogos) seguem o molde
`platform_admins`: sem GRANT direto, acesso via SECURITY DEFINER/sessões helper.

## SA-D04 · Interface `BillingProvider` + factory por configuração

`app/services/billing/provider.py` define o contrato (ABC): `create_customer`,
`update_customer`, `create_checkout`, `create_portal`, `create_subscription`,
`update_subscription` (up/downgrade com proration), `cancel_subscription(at_period_end)`,
`reactivate_subscription`, `pause_subscription`, `resume_subscription`,
`refund_payment`, `get_customer`, `get_subscription`, `get_invoices`,
`sync_subscription`, `parse_webhook(headers, body) -> list[ProviderEvent]`
(verificação de assinatura DENTRO do provider), `sync_plan(plan)` (espelha
Product/Price). Implementações: `StripeBillingProvider` (único lugar que importa
`stripe`), `MockBillingProvider` (dev/testes, estado em memória/banco).
Factory `get_billing_provider()` lê `settings.billing_provider`
(`BILLING_PROVIDER=mock|stripe`; **default `mock`** — fail-safe sem chave).
Asaas/MercadoPago futuros = nova classe + config, zero mudança de regra.

**Camada de negócio:** `app/services/billing/service.py` (SubscriptionService) é o
ÚNICO chamador do provider; routers (tenant `/billing/*` e plataforma
`/platform/billing/*`) chamam só o service. Nenhum outro módulo importa Stripe.

## SA-D05 · Stripe: Checkout + Customer Portal + Prices (best practices oficiais)

- Assinatura inicia por **Checkout Session `mode=subscription`** (nunca PaymentIntent manual).
- Autosserviço (trocar cartão, upgrade/downgrade/cancelar) via **Customer Portal**.
- Catálogo local espelhado em **Products/Prices** (nunca o objeto `plan` deprecado).
- **Nunca** enviar `payment_method_types` (payment methods dinâmicos do dashboard).
- Dunning: **Smart Retries da Stripe**; `payment_attempts` local só REGISTRA o que
  os webhooks `invoice.payment_failed` reportam (attempt_count, próximo retry).
- Webhook: assinatura verificada com `STRIPE_WEBHOOK_SECRET`; persistir bruto em
  `webhook_events` idempotente ANTES de processar; falha marca `failed` e permite
  replay (`POST /platform/billing/webhook-events/{id}/reprocess`).
- Chaves: só via env/settings (nunca código); recomendação registrada em
  `blockers.md` B-02 de usar **restricted key** com permissões mínimas.
- API version alvo: `2026-06-24.dahlia` (pinada no provider).

## SA-D06 · Ciclo de vida e enforcement

- **Transições reais:** provider `stripe` → status dirigido por webhook;
  provider `manual` → job diário (`app/services/billing/lifecycle.py`, exposto em
  `/internal/billing/run-lifecycle` p/ cron n8n, molde dos crons do gestor):
  `trial` vencido → `past_due` (grace configurável) → `canceled` (após N dias).
- **Entitlement em 3 níveis** (`app/core/entitlements.py`): `full` (trial/active),
  `restricted` (past_due — bloqueia só recursos pagos, mantém leitura/agenda do dia),
  `blocked` (canceled/suspended). Dependencies FastAPI `require_feature(key)` e
  `check_limit(key)` aplicadas nos pontos de criação (barbeiro/unidade) — hoje
  ZERO enforcement existe; entra de forma **fail-open com log** primeiro (warning),
  vira fail-closed por flag `BILLING_ENFORCEMENT=hard` após validação em prod.
- Upgrade aplica entitlements imediatamente; downgrade aplica no fim do período
  (ou imediato com proration, decisão por chamada), nunca deletando dados —
  recursos acima do limite ficam read-only, não são destruídos.

## SA-D07 · Documentação da missão vive em `docs/superadmin/` do monorepo

O painel atravessa backend+frontends; o monorepo é a casa documental (CLAUDE.md,
DECISIONS.md). O repo `barbearia-superadmin` ganha ponteiro no README.

## SA-D09 · Tela "Minha Assinatura" do tenant: handoff documentado (não codada agora)

O repo do tenant tem duas feature branches em voo (`feat/multi-tenant-org-id` e
`feat/kernel-ia-launcher`) não mescladas. Editar qualquer uma criaria conflito
de merge. O CONTRATO do cliente está pronto e testado (`GET /billing/plans`,
`GET /billing/subscription` com entitlements, `POST /billing/checkout`,
`POST /billing/portal`, `GET /billing/invoices` — owner/manager). A tela é
estender `components/empresa/plano-card.tsx` em `/admin/empresa` (nunca
`/admin/assinaturas`, que é mensalidade de cliente final) com: botão
"Assinar/fazer upgrade" → checkout, "Gerenciar assinatura" (se `has_gateway`)
→ portal, e lista de faturas. ~30 min quando as branches assentarem.

## SA-D08 · Métricas executivas calculadas on-read (sem ETL)

`/platform/metrics` calcula MRR/ARR/churn/LTV/séries via SQL agregado (funções
SECURITY DEFINER, molde 0021) sobre `subscriptions`+`invoices`+`billing_payments`.
Sem tabela de snapshot por ora (volume atual: dezenas de orgs). Quando doer,
materializar `metrics_daily` — decisão adiada de propósito (YAGNI).
