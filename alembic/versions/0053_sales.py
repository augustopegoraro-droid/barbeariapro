"""Venda de produtos — Fase 3 do módulo de Produtos/Estoque/Vendas
(plano em /Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Cria `sales`/`sale_items`/`sale_payments`: domínio paralelo a `Appointment`/
`AppointmentItem`/`Payment`, opcionalmente ligado a `appointments.id`
(`appointment_id` nullable = venda de balcão pura), nunca alterando as
tabelas núcleo do Financeiro/Agenda. `sale_payments.method` reaproveita o
enum `payment_method` já existente (não duplica). Baixa de estoque é
emitida por `app/services/inventory.py::apply_stock_movement` fora desta
migration (tipo `saida_venda`, já presente no enum `stock_movement_type`
desde a 0052). Molde de `commission_transfers`/0050: RLS + FORCE, GRANT ao
`barber_app`.

Revision ID: 0053_sales
Revises: 0052_stock_movements
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0053_sales"
down_revision = "0052_stock_movements"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_SALE_STATUSES = ("concluida", "cancelada")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_SALE_STATUSES, name="sale_status").create(bind, checkfirst=False)

    op.create_table(
        "sales",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "unit_id", sa.BigInteger,
            sa.ForeignKey("units.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "client_id", sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "appointment_id", sa.BigInteger,
            sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(*_SALE_STATUSES, name="sale_status", create_type=False),
            nullable=False,
            server_default="concluida",
        ),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("total_amount >= 0", name="sales_total_amount_nonneg"),
    )
    op.create_index("idx_sales_org_created", "sales", ["organization_id", "created_at"])
    op.create_index("idx_sales_org_appointment", "sales", ["organization_id", "appointment_id"])
    op.create_index("idx_sales_org_client", "sales", ["organization_id", "client_id"])

    op.create_table(
        "sale_items",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "sale_id", sa.BigInteger,
            sa.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "variant_id", sa.BigInteger,
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("qty", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price_charged", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_cost_snapshot", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.CheckConstraint("qty > 0", name="sale_items_qty_positive"),
        sa.CheckConstraint("unit_price_charged >= 0", name="sale_items_price_nonneg"),
        sa.CheckConstraint("unit_cost_snapshot >= 0", name="sale_items_cost_nonneg"),
    )
    op.create_index("idx_sale_items_org_sale", "sale_items", ["organization_id", "sale_id"])
    op.create_index("idx_sale_items_org_variant", "sale_items", ["organization_id", "variant_id"])

    op.create_table(
        "sale_payments",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "sale_id", sa.BigInteger,
            sa.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "method",
            postgresql.ENUM(*("dinheiro", "cartao", "pix"), name="payment_method", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "paid_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("amount > 0", name="sale_payments_amount_positive"),
    )
    op.create_index("idx_sale_payments_org_sale", "sale_payments", ["organization_id", "sale_id"])

    for table in ("sales", "sale_items", "sale_payments"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    for table in ("sale_payments", "sale_items", "sales"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(table)
    op.execute("DROP TYPE sale_status")
