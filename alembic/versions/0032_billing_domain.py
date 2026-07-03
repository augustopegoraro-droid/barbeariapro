"""domínio de billing do SaaS: faturas, pagamentos, cupons, créditos, webhooks (M7)

Revision ID: 0032_billing_domain
Revises: 0031_platform_onboarding
Create Date: 2026-07-03

Aditivo. Implementa o domínio decidido em docs/superadmin/decisions.md
(SA-D01…SA-D06). Nada aqui altera comportamento existente: são colunas novas
com default, tabelas novas e backfills idempotentes.

- Enum `subscription_status` ganha `paused` e `incomplete` (ADD VALUE).
- `plans` ganha slug/description/is_active/sort_order/stripe_product_id;
  `subscriptions` ganha provider/ids externos/cancel_at_period_end/trial_end/
  paused_at/resumes_at/updated_at.
- Catálogos globais (molde `plans`, sem RLS): plan_prices, feature_flags,
  plan_features, plan_limits, coupons.
- Tabelas por org (RLS `tenant_isolation`, molde 0023): billing_customers,
  invoices, billing_payments, payment_attempts, discounts, billing_credits,
  usage_metrics, billing_events.
- `webhook_events` sem RLS (evento chega antes da org ser resolvida) — nunca
  exposta a rotas de tenant.
- Backfills: plans.slug (dedupe por id), plan_limits (units/barbers a partir do
  legado max_units/max_barbers), plan_prices mensal (price_month).
- Funções SECURITY DEFINER de resolução p/ webhooks (molde 0020).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0032_billing_domain"
down_revision = "0031_platform_onboarding"
branch_labels = None
depends_on = None

# Tabelas por org que recebem o bloco RLS padrão.
_RLS_TABLES = (
    "billing_customers",
    "invoices",
    "billing_payments",
    "payment_attempts",
    "discounts",
    "billing_credits",
    "usage_metrics",
    "billing_events",
)

_FUNCTIONS = (
    "app_billing_org_by_customer(text, text)",
    "app_billing_org_by_provider_subscription(text, text)",
)


def _rls(table: str, grants: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (organization_id = current_setting('app.current_org_id', true)::bigint)
        """
    )
    op.execute(f"GRANT {grants} ON {table} TO barber_app")


def upgrade() -> None:
    # ── enum: novos estados de assinatura ────────────────────────────────────
    op.execute("ALTER TYPE subscription_status ADD VALUE IF NOT EXISTS 'paused'")
    op.execute("ALTER TYPE subscription_status ADD VALUE IF NOT EXISTS 'incomplete'")

    # ── plans: identidade estável + espelho Stripe ───────────────────────────
    op.add_column("plans", sa.Column("slug", sa.Text(), nullable=True))
    op.add_column("plans", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "plans",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "plans",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("plans", sa.Column("stripe_product_id", sa.Text(), nullable=True))
    # Backfill de slug a partir do nome; dedupe apensando o id.
    op.execute(
        """
        UPDATE plans SET slug = trim(both '-' from
            regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g'))
        WHERE slug IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans p SET slug = p.slug || '-' || p.id
        WHERE EXISTS (
            SELECT 1 FROM plans q WHERE q.slug = p.slug AND q.id < p.id
        )
        """
    )
    op.create_unique_constraint("plans_slug_unique", "plans", ["slug"])

    # ── subscriptions: provider + ciclo de vida ──────────────────────────────
    op.add_column(
        "subscriptions",
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
    )
    op.add_column("subscriptions", sa.Column("provider_customer_id", sa.Text(), nullable=True))
    op.add_column(
        "subscriptions", sa.Column("provider_subscription_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("subscriptions", sa.Column("trial_end", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("paused_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("resumes_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX subscriptions_provider_sid_unique
        ON subscriptions (provider, provider_subscription_id)
        WHERE provider_subscription_id IS NOT NULL
        """
    )

    # ── catálogos globais (molde plans: sem RLS) ─────────────────────────────
    op.create_table(
        "plan_prices",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'brl'")),
        sa.Column("provider_price_id", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("cycle IN ('monthly', 'yearly')", name="plan_prices_cycle_valid"),
        sa.CheckConstraint("amount >= 0", name="plan_prices_amount_nonneg"),
        sa.UniqueConstraint("plan_id", "cycle", name="plan_prices_plan_cycle_unique"),
    )
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "plan_features",
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("feature_key", sa.Text(), sa.ForeignKey("feature_flags.key", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "plan_limits",
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("limit_key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=True),
        sa.CheckConstraint("value IS NULL OR value >= 0", name="plan_limits_value_nonneg"),
    )
    op.create_table(
        "coupons",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("percent_off", sa.Numeric(5, 2), nullable=True),
        sa.Column("amount_off", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'brl'")),
        sa.Column("duration", sa.Text(), nullable=False, server_default=sa.text("'once'")),
        sa.Column("duration_months", sa.Integer(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("times_redeemed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("provider_coupon_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("(percent_off IS NOT NULL) <> (amount_off IS NOT NULL)", name="coupons_percent_xor_amount"),
        sa.CheckConstraint("percent_off IS NULL OR (percent_off > 0 AND percent_off <= 100)", name="coupons_percent_range"),
        sa.CheckConstraint("amount_off IS NULL OR amount_off > 0", name="coupons_amount_positive"),
        sa.CheckConstraint("duration IN ('once', 'repeating', 'forever')", name="coupons_duration_valid"),
        sa.CheckConstraint("duration <> 'repeating' OR duration_months > 0", name="coupons_repeating_months"),
    )
    for table in ("plan_prices", "feature_flags", "plan_features", "plan_limits"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO barber_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON coupons TO barber_app")

    # ── tabelas por org (RLS) ────────────────────────────────────────────────
    op.create_table(
        "billing_customers",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_customer_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "provider_customer_id", name="billing_customers_provider_cid_unique"),
        sa.UniqueConstraint("provider", "organization_id", name="billing_customers_provider_org_unique"),
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", sa.BigInteger, sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("provider_invoice_id", sa.Text(), nullable=True),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("amount_due", sa.Numeric(10, 2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'brl'")),
        sa.Column("period_start", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("period_end", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("due_date", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("hosted_invoice_url", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('draft', 'open', 'paid', 'void', 'uncollectible')", name="invoices_status_valid"),
        sa.CheckConstraint("amount_due >= 0", name="invoices_amount_due_nonneg"),
        sa.CheckConstraint("amount_paid >= 0", name="invoices_amount_paid_nonneg"),
        sa.UniqueConstraint("provider", "provider_invoice_id", name="invoices_provider_iid_unique"),
    )
    op.create_index("idx_invoices_org", "invoices", ["organization_id"])
    op.create_index("idx_invoices_status", "invoices", ["status"])
    op.create_table(
        "billing_payments",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("invoice_id", sa.BigInteger, sa.ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("provider_payment_id", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'brl'")),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded', 'partially_refunded')",
            name="billing_payments_status_valid",
        ),
        sa.CheckConstraint("amount >= 0", name="billing_payments_amount_nonneg"),
        sa.UniqueConstraint("provider", "provider_payment_id", name="billing_payments_provider_pid_unique"),
    )
    op.create_index("idx_billing_payments_org", "billing_payments", ["organization_id"])
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("invoice_id", sa.BigInteger, sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider_error_code", sa.Text(), nullable=True),
        sa.Column("provider_error_message", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("attempt_number > 0", name="payment_attempts_number_positive"),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name="payment_attempts_status_valid"),
        sa.UniqueConstraint("invoice_id", "attempt_number", name="payment_attempts_invoice_n_unique"),
    )
    op.create_index("idx_payment_attempts_org", "payment_attempts", ["organization_id"])
    op.create_table(
        "discounts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", sa.BigInteger, sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("coupon_id", sa.BigInteger, sa.ForeignKey("coupons.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider_discount_id", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ends_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_admin_id", sa.BigInteger, sa.ForeignKey("platform_admins.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_discounts_org", "discounts", ["organization_id"])
    op.create_table(
        "billing_credits",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'brl'")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_by_admin_id", sa.BigInteger, sa.ForeignKey("platform_admins.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount <> 0", name="billing_credits_amount_nonzero"),
        sa.CheckConstraint("source IN ('admin', 'refund', 'promo', 'consumption')", name="billing_credits_source_valid"),
    )
    op.create_index("idx_billing_credits_org", "billing_credits", ["organization_id"])
    op.create_table(
        "usage_metrics",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "metric_key", "period", name="usage_metrics_org_key_period_unique"),
        sa.CheckConstraint("value >= 0", name="usage_metrics_value_nonneg"),
    )
    op.create_table(
        "billing_events",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", sa.BigInteger, sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("invoice_id", sa.BigInteger, sa.ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.BigInteger, nullable=True),
        sa.Column("actor_label", sa.Text(), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "actor_type IN ('system', 'platform_admin', 'tenant', 'provider')",
            name="billing_events_actor_valid",
        ),
    )
    op.create_index("idx_billing_events_org", "billing_events", ["organization_id"])
    op.create_index("idx_billing_events_type", "billing_events", ["event_type"])

    # RLS + grants por tabela (append-only não ganha UPDATE).
    _rls("billing_customers", "SELECT, INSERT, UPDATE")
    _rls("invoices", "SELECT, INSERT, UPDATE")
    _rls("billing_payments", "SELECT, INSERT, UPDATE")
    _rls("payment_attempts", "SELECT, INSERT, UPDATE")
    _rls("discounts", "SELECT, INSERT, UPDATE")
    _rls("billing_credits", "SELECT, INSERT")
    _rls("usage_metrics", "SELECT, INSERT, UPDATE")
    _rls("billing_events", "SELECT, INSERT")

    # ── webhook_events (sem RLS — chega antes da org; nunca vai a rota tenant)
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.BigInteger, nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'received'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "event_id", name="webhook_events_provider_eid_unique"),
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'failed', 'skipped')",
            name="webhook_events_status_valid",
        ),
    )
    op.create_index("idx_webhook_events_status", "webhook_events", ["status"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON webhook_events TO barber_app")

    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")

    # ── backfills idempotentes ───────────────────────────────────────────────
    op.execute(
        """
        INSERT INTO plan_limits (plan_id, limit_key, value)
        SELECT id, 'units', max_units FROM plans
        ON CONFLICT (plan_id, limit_key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_limits (plan_id, limit_key, value)
        SELECT id, 'barbers', max_barbers FROM plans
        ON CONFLICT (plan_id, limit_key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_prices (plan_id, cycle, amount)
        SELECT id, 'monthly', price_month FROM plans
        ON CONFLICT (plan_id, cycle) DO NOTHING
        """
    )

    # ── resolução p/ webhooks (molde 0020) ───────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_billing_org_by_customer(
            p_provider text, p_customer_id text
        )
        RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT organization_id FROM billing_customers
            WHERE provider = p_provider AND provider_customer_id = p_customer_id
            LIMIT 1
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_billing_org_by_provider_subscription(
            p_provider text, p_subscription_id text
        )
        RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT organization_id FROM subscriptions
            WHERE provider = p_provider AND provider_subscription_id = p_subscription_id
            LIMIT 1
        $$
        """
    )
    for fn in _FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO barber_app")


def downgrade() -> None:
    for fn in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.drop_table("webhook_events")
    for table in reversed(_RLS_TABLES):
        op.drop_table(table)
    op.drop_table("coupons")
    op.drop_table("plan_limits")
    op.drop_table("plan_features")
    op.drop_table("feature_flags")
    op.drop_table("plan_prices")
    op.execute("DROP INDEX IF EXISTS subscriptions_provider_sid_unique")
    for col in (
        "updated_at", "resumes_at", "paused_at", "trial_end",
        "cancel_at_period_end", "provider_subscription_id",
        "provider_customer_id", "provider",
    ):
        op.drop_column("subscriptions", col)
    op.drop_constraint("plans_slug_unique", "plans")
    for col in ("stripe_product_id", "sort_order", "is_active", "description", "slug"):
        op.drop_column("plans", col)
    # Valores de enum não são removíveis com segurança — permanecem (aditivo).
