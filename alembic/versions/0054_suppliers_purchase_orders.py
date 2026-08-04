"""Fornecedores e pedidos de compra — Fase 5 do módulo de Produtos/Estoque/
Vendas (plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Cria `suppliers`/`purchase_orders`/`purchase_order_items`. `entrada_compra`
já existe no enum `stock_movement_type` desde a 0052 — esta migration não
mexe nele. Molde de `sales`/0053: RLS + FORCE, GRANT SELECT/INSERT/UPDATE ao
`barber_app` (sem DELETE — arquivar fornecedor via `active`, cancelar pedido
via `status`, nunca apagar linha).

Revision ID: 0054_suppliers_purchase_orders
Revises: 0053_sales
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0054_suppliers_purchase_orders"
down_revision = "0053_sales"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_PO_STATUSES = ("rascunho", "enviado", "recebido_parcial", "recebido", "cancelado")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_PO_STATUSES, name="purchase_order_status").create(bind, checkfirst=False)

    op.create_table(
        "suppliers",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("document", sa.Text, nullable=True),
        sa.Column("phone", sa.Text, nullable=True),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_suppliers_org_active", "suppliers", ["organization_id", "active"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "supplier_id", sa.BigInteger,
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(*_PO_STATUSES, name="purchase_order_status", create_type=False),
            nullable=False,
            server_default="rascunho",
        ),
        sa.Column(
            "order_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("expected_date", sa.Date, nullable=True),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_purchase_orders_org_status", "purchase_orders", ["organization_id", "status"]
    )
    op.create_index(
        "idx_purchase_orders_org_supplier", "purchase_orders", ["organization_id", "supplier_id"]
    )

    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "purchase_order_id", sa.BigInteger,
            sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "variant_id", sa.BigInteger,
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("qty_ordered", sa.Numeric(12, 3), nullable=False),
        sa.Column("qty_received", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=False),
        sa.CheckConstraint("qty_ordered > 0", name="purchase_order_items_qty_ordered_positive"),
        sa.CheckConstraint("qty_received >= 0", name="purchase_order_items_qty_received_nonneg"),
        sa.CheckConstraint("unit_cost >= 0", name="purchase_order_items_unit_cost_nonneg"),
    )
    op.create_index(
        "idx_purchase_order_items_org_po",
        "purchase_order_items",
        ["organization_id", "purchase_order_id"],
    )
    op.create_index(
        "idx_purchase_order_items_org_variant",
        "purchase_order_items",
        ["organization_id", "variant_id"],
    )

    for table in ("suppliers", "purchase_orders", "purchase_order_items"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    for table in ("purchase_order_items", "purchase_orders", "suppliers"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(table)
    op.execute("DROP TYPE purchase_order_status")
