"""Assinatura online do cliente final via Stripe Connect (Feature 2).

Três peças:

1. `organizations` ganha os campos da **connected account** da barbearia
   (id da conta na Stripe + os 3 flags de capacidade que a Stripe devolve +
   carimbo do último sync) e a **taxa da plataforma por org**
   (`platform_fee_pct`, NULL = usa o default global `PLATFORM_FEE_PCT_DEFAULT`).
   ALTER puro: a tabela já tem RLS/GRANT — nada novo aqui (molde da 0059).

2. `membership_orders` — o pedido de compra online + o registro do dinheiro.
   Molde `feed_posts`/0061 (RLS + FORCE + GRANT sem DELETE — é registro
   financeiro, nunca se apaga; um pedido morto vira `expired`/`canceled`).
   Guarda **snapshots** do plano (preço/usos/duração/combo), no mesmo espírito
   de `client_memberships`: editar o plano depois não reescreve o pedido.
   `UNIQUE (provider, provider_session_id)` é a idempotência forte do webhook:
   uma Checkout Session da Stripe corresponde a no máximo um pedido.

3. `app_org_id_by_connected_account` (SECURITY DEFINER, molde
   `app_billing_org_by_customer`/0032): o webhook da Stripe chega SEM tenant na
   sessão e `organizations` tem RLS — sem essa função, um SELECT pré-tenant não
   veria linha alguma.

Revision ID: 0062_stripe_connect
Revises: 0061_feed_posts
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0062_stripe_connect"
down_revision = "0061_feed_posts"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    # ── 1. organizations: connected account + taxa da plataforma ─────────────
    op.add_column(
        "organizations", sa.Column("stripe_connected_account_id", sa.Text, nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column(
            "stripe_connect_charges_enabled", sa.Boolean, nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "stripe_connect_details_submitted", sa.Boolean, nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "stripe_connect_payouts_enabled", sa.Boolean, nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("stripe_connect_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations", sa.Column("platform_fee_pct", sa.Numeric(5, 2), nullable=True)
    )
    # Índice PARCIAL: uma conta da Stripe pertence a uma única org, mas a
    # esmagadora maioria das orgs tem NULL (e NULL não colide em UNIQUE parcial).
    op.execute(
        "CREATE UNIQUE INDEX idx_organizations_connected_account "
        "ON organizations (stripe_connected_account_id) "
        "WHERE stripe_connected_account_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE organizations ADD CONSTRAINT organizations_platform_fee_pct_range "
        "CHECK (platform_fee_pct IS NULL OR platform_fee_pct BETWEEN 0 AND 100)"
    )

    # ── 2. membership_orders ────────────────────────────────────────────────
    op.create_table(
        "membership_orders",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "public_id", sa.Uuid, nullable=False, unique=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "client_id", sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False,
        ),
        # Sessão do site que originou a compra (D-79). SET NULL: revogar a
        # sessão não pode apagar o registro do dinheiro.
        sa.Column(
            "client_session_id", sa.BigInteger,
            sa.ForeignKey("client_sessions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "plan_id", sa.BigInteger,
            sa.ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False,
        ),
        # ── snapshots do plano no momento do pedido ─────────────────────────
        sa.Column("plan_name", sa.Text, nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("included_uses", sa.Integer, nullable=True),
        sa.Column("duration_days", sa.Integer, nullable=True),
        sa.Column("combo_snapshot", postgresql.JSONB, nullable=True),
        # ── ciclo de vida ───────────────────────────────────────────────────
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "provider", sa.Text, nullable=False, server_default=sa.text("'stripe_connect'")
        ),
        sa.Column("provider_session_id", sa.Text, nullable=True),
        sa.Column("provider_payment_intent_id", sa.Text, nullable=True),
        sa.Column("provider_charge_id", sa.Text, nullable=True),
        sa.Column("connected_account_id", sa.Text, nullable=True),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("application_fee_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'brl'")),
        sa.Column("payment_method_detail", sa.Text, nullable=True),
        # Preenchido SÓ na confirmação do webhook — é o que garante que ninguém
        # ganha pacote sem pagar (e a 2ª confirmação vira no-op idempotente).
        sa.Column(
            "client_membership_id", sa.BigInteger,
            sa.ForeignKey("client_memberships.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'expired', 'canceled')",
            name="membership_orders_status_valid",
        ),
        sa.CheckConstraint("amount_cents >= 0", name="membership_orders_amount_nonneg"),
        sa.CheckConstraint(
            "application_fee_cents >= 0 AND application_fee_cents <= amount_cents",
            name="membership_orders_fee_within_amount",
        ),
        sa.UniqueConstraint(
            "provider", "provider_session_id", name="membership_orders_provider_session_unique"
        ),
    )
    op.execute(
        "CREATE INDEX idx_membership_orders_org_status ON membership_orders "
        "(organization_id, status)"
    )

    op.execute("ALTER TABLE membership_orders ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON membership_orders "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE membership_orders FORCE ROW LEVEL SECURITY")
    # Sem DELETE de propósito: registro financeiro não se apaga.
    op.execute("GRANT SELECT, INSERT, UPDATE ON membership_orders TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")

    # ── 3. resolução de org p/ o webhook (molde 0020/0032) ──────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_org_id_by_connected_account(p_account_id text)
        RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT id FROM organizations
            WHERE stripe_connected_account_id = p_account_id
              AND deleted_at IS NULL
            LIMIT 1
        $$
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_org_id_by_connected_account(text) TO barber_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_org_id_by_connected_account(text)")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON membership_orders")
    op.execute("ALTER TABLE membership_orders DISABLE ROW LEVEL SECURITY")
    op.drop_table("membership_orders")
    op.execute(
        "ALTER TABLE organizations DROP CONSTRAINT IF EXISTS "
        "organizations_platform_fee_pct_range"
    )
    op.execute("DROP INDEX IF EXISTS idx_organizations_connected_account")
    for col in (
        "platform_fee_pct",
        "stripe_connect_synced_at",
        "stripe_connect_payouts_enabled",
        "stripe_connect_details_submitted",
        "stripe_connect_charges_enabled",
        "stripe_connected_account_id",
    ):
        op.drop_column("organizations", col)
