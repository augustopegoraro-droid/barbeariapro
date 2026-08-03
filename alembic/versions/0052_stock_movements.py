"""Movimentação de estoque — Fase 2 do módulo de Produtos/Estoque/Vendas
(plano em /Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Cria `stock_movements` (append-only, fonte de auditoria do saldo de
`product_variants.stock_qty`). O tipo PG `stock_movement_type` já nasce com os
6 valores do plano completo (entrada_compra/entrada_ajuste/saida_venda/
saida_ajuste/perda/inventario) mesmo que esta fase só emita ajuste/perda
manuais — `ALTER TYPE ... ADD VALUE` não roda na mesma transação que já usa o
valor novo, então pré-declarar evita dor de cabeça nas Fases 3 (venda) e 6
(inventário).

Toda escrita passa por `app/services/inventory.py::apply_stock_movement`
(lock `FOR UPDATE` na variante). Molde de `commission_transfers`/0050: RLS +
FORCE, GRANT ao `barber_app`.

Revision ID: 0052_stock_movements
Revises: 0051_product_catalog
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0052_stock_movements"
down_revision = "0051_product_catalog"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_STOCK_MOVEMENT_TYPES = (
    "entrada_compra", "entrada_ajuste", "saida_venda", "saida_ajuste", "perda", "inventario",
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_STOCK_MOVEMENT_TYPES, name="stock_movement_type").create(
        bind, checkfirst=False
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "variant_id", sa.BigInteger,
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "movement_type",
            postgresql.ENUM(*_STOCK_MOVEMENT_TYPES, name="stock_movement_type", create_type=False),
            nullable=False,
        ),
        sa.Column("qty_delta", sa.Numeric(12, 3), nullable=False),
        sa.Column("qty_after", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("reference_type", sa.Text, nullable=True),
        sa.Column("reference_id", sa.BigInteger, nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("qty_delta <> 0", name="stock_movements_qty_delta_nonzero"),
    )
    op.create_index(
        "idx_stock_movements_org_variant",
        "stock_movements",
        ["organization_id", "variant_id", "created_at"],
    )

    op.execute("ALTER TABLE stock_movements ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON stock_movements "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE stock_movements FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON stock_movements TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON stock_movements")
    op.execute("ALTER TABLE stock_movements DISABLE ROW LEVEL SECURITY")
    op.drop_table("stock_movements")
    op.execute("DROP TYPE stock_movement_type")
