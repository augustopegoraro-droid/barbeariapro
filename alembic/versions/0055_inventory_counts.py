"""Contagem física de estoque — Fase 6 do módulo de Produtos/Estoque/Vendas
(plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Cria `inventory_counts`/`inventory_count_items`. `inventario` já existe no
enum `stock_movement_type` desde a 0052 — esta migration não mexe nele.
Molde de `suppliers`/0054: RLS + FORCE, GRANT SELECT/INSERT/UPDATE ao
`barber_app` (sem DELETE — finalizar via `status`, nunca apagar linha).

Revision ID: 0055_inventory_counts
Revises: 0054_suppliers_purchase_orders
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0055_inventory_counts"
down_revision = "0054_suppliers_purchase_orders"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_COUNT_STATUSES = ("aberto", "finalizado")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_COUNT_STATUSES, name="inventory_count_status").create(bind, checkfirst=False)

    op.create_table(
        "inventory_counts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(*_COUNT_STATUSES, name="inventory_count_status", create_type=False),
            nullable=False,
            server_default="aberto",
        ),
        sa.Column(
            "started_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finalized_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger, nullable=True),
    )
    op.create_index(
        "idx_inventory_counts_org_status", "inventory_counts", ["organization_id", "status"]
    )

    op.create_table(
        "inventory_count_items",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "inventory_count_id", sa.BigInteger,
            sa.ForeignKey("inventory_counts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "variant_id", sa.BigInteger,
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("expected_qty", sa.Numeric(12, 3), nullable=False),
        sa.Column("counted_qty", sa.Numeric(12, 3), nullable=True),
        sa.UniqueConstraint(
            "inventory_count_id", "variant_id", name="inventory_count_items_count_variant_uq"
        ),
    )
    op.create_index(
        "idx_inventory_count_items_org_count",
        "inventory_count_items",
        ["organization_id", "inventory_count_id"],
    )
    op.create_index(
        "idx_inventory_count_items_org_variant",
        "inventory_count_items",
        ["organization_id", "variant_id"],
    )

    for table in ("inventory_counts", "inventory_count_items"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    for table in ("inventory_count_items", "inventory_counts"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(table)
    op.execute("DROP TYPE inventory_count_status")
