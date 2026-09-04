"""Clube de assinatura — add-ons (Bump A/C, D-104 Fase 4).

Plano em /Users/apleandro/.claude/plans/piped-percolating-kazoo.md.

Aditivo, não quebra nada:
- `membership_addons` — catálogo de add-ons por org (produto/uso_extra/escopo),
  ativados/arquivados via `is_active`. Molde de `product_purchase_requests`/0057
  (CHECK "pelo menos um dos dois" por kind).
- `client_membership_addons` — add-ons contratados por uma assinatura (1 linha
  por add-on ativo), snapshot imutável no momento da venda/renovação. Molde de
  `membership_offer_events`/0065 (RLS+FORCE, GRANT append-only).
- `membership_orders` ganha `addons_snapshot` jsonb — trava os add-ons
  escolhidos no checkout público, consumido pelo webhook em `_confirm_order`.

Revision ID: 0066_membership_addons
Revises: 0065_membership_offers
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0066_membership_addons"
down_revision = "0065_membership_offers"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_KINDS = ("produto", "uso_extra", "escopo")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_KINDS, name="membership_addon_kind").create(bind, checkfirst=False)

    op.create_table(
        "membership_addons",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(*_KINDS, name="membership_addon_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "variant_id", sa.BigInteger,
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=True,
        ),
        sa.Column("extra_uses", sa.Integer(), nullable=True),
        sa.Column(
            "extra_service_id", sa.BigInteger,
            sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("price >= 0", name="membership_addons_price_nonneg"),
        sa.CheckConstraint(
            "extra_uses IS NULL OR extra_uses > 0", name="membership_addons_extra_uses_pos"
        ),
        sa.CheckConstraint(
            "(kind = 'produto' AND variant_id IS NOT NULL) OR "
            "(kind = 'uso_extra' AND extra_uses IS NOT NULL) OR "
            "(kind = 'escopo' AND extra_service_id IS NOT NULL)",
            name="membership_addons_target_matches_kind",
        ),
    )
    op.create_index("idx_membership_addons_org", "membership_addons", ["organization_id"])

    op.create_table(
        "client_membership_addons",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "client_membership_id", sa.BigInteger,
            sa.ForeignKey("client_memberships.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "addon_id", sa.BigInteger,
            sa.ForeignKey("membership_addons.id", ondelete="RESTRICT"), nullable=False,
        ),
        # ── snapshot imutável no momento da venda/renovação ────────────────
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "kind_snapshot",
            postgresql.ENUM(*_KINDS, name="membership_addon_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("price_snapshot", sa.Numeric(10, 2), nullable=False),
        sa.Column("extra_uses_snapshot", sa.Integer(), nullable=True),
        sa.Column(
            "extra_service_id_snapshot", sa.BigInteger,
            sa.ForeignKey("services.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "variant_id_snapshot", sa.BigInteger,
            sa.ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "price_snapshot >= 0", name="client_membership_addons_price_nonneg"
        ),
    )
    op.create_index(
        "idx_client_membership_addons_membership",
        "client_membership_addons",
        ["client_membership_id"],
    )

    op.add_column(
        "membership_orders",
        sa.Column(
            "addons_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    for table in ("membership_addons", "client_membership_addons"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Catálogo (arquiva via is_active) — sem DELETE.
    op.execute("GRANT SELECT, INSERT, UPDATE ON membership_addons TO barber_app")
    # Add-ons contratados — append-only, molde membership_offer_events/0065.
    op.execute("GRANT SELECT, INSERT ON client_membership_addons TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.drop_column("membership_orders", "addons_snapshot")
    for table in ("client_membership_addons", "membership_addons"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("client_membership_addons")
    op.drop_table("membership_addons")
    op.execute("DROP TYPE IF EXISTS membership_addon_kind")
