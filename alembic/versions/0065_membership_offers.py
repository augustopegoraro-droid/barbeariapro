"""Clube de assinatura do cliente final — segmentação de catálogo + order bumps.

Plano em /Users/apleandro/.claude/plans/cheerful-wishing-cake.md.

Aditivo, não quebra nada:
- `membership_plans` ganha campos de vitrine/segmentação (`audience`, `category`,
  `headline`, `perks`, `badge`, `display_order`, `is_featured`) — todos com
  default, backfill no-op.
- `membership_offer_events` — log append-only de cada oferta de plano feita nas
  3 superfícies (booking / conclusao / assinatura), com o desfecho
  (`shown`/`accepted`/`dismissed`). Alimenta o painel de conversão e serve de
  guarda contra reexibir a mesma oferta. Molde de `stock_movements`/0052:
  RLS + FORCE, GRANT só SELECT/INSERT (append-only).

Revision ID: 0065_membership_offers
Revises: 0064_expense_details
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0065_membership_offers"
down_revision = "0064_expense_details"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_AUDIENCES = ("masculino", "feminino", "unissex")
_SURFACES = ("booking", "conclusao", "assinatura")
_OUTCOMES = ("shown", "accepted", "dismissed")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_AUDIENCES, name="plan_audience").create(bind, checkfirst=False)
    postgresql.ENUM(*_SURFACES, name="membership_offer_surface").create(bind, checkfirst=False)
    postgresql.ENUM(*_OUTCOMES, name="membership_offer_outcome").create(bind, checkfirst=False)

    op.add_column(
        "membership_plans",
        sa.Column(
            "audience",
            postgresql.ENUM(*_AUDIENCES, name="plan_audience", create_type=False),
            nullable=False,
            server_default="unissex",
        ),
    )
    op.add_column("membership_plans", sa.Column("category", sa.Text(), nullable=True))
    op.add_column("membership_plans", sa.Column("headline", sa.Text(), nullable=True))
    op.add_column(
        "membership_plans",
        sa.Column(
            "perks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("membership_plans", sa.Column("badge", sa.Text(), nullable=True))
    op.add_column(
        "membership_plans",
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "membership_plans",
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "membership_offer_events",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "surface",
            postgresql.ENUM(*_SURFACES, name="membership_offer_surface", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            postgresql.ENUM(*_OUTCOMES, name="membership_offer_outcome", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "plan_id", sa.BigInteger,
            sa.ForeignKey("membership_plans.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "client_id", sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "client_session_id", sa.BigInteger,
            sa.ForeignKey("client_sessions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "appointment_id", sa.BigInteger,
            sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("shown_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("shown_amount IS NULL OR shown_amount >= 0", name="membership_offer_events_amount_nonneg"),
    )
    op.create_index(
        "idx_membership_offer_events_org_created",
        "membership_offer_events",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "idx_membership_offer_events_org_surface",
        "membership_offer_events",
        ["organization_id", "surface", "outcome"],
    )

    op.execute("ALTER TABLE membership_offer_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON membership_offer_events "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE membership_offer_events FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON membership_offer_events TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON membership_offer_events")
    op.execute("ALTER TABLE membership_offer_events DISABLE ROW LEVEL SECURITY")
    op.drop_table("membership_offer_events")
    for col in (
        "is_featured", "display_order", "badge", "perks", "headline", "category", "audience",
    ):
        op.drop_column("membership_plans", col)
    op.execute("DROP TYPE IF EXISTS membership_offer_outcome")
    op.execute("DROP TYPE IF EXISTS membership_offer_surface")
    op.execute("DROP TYPE IF EXISTS plan_audience")
