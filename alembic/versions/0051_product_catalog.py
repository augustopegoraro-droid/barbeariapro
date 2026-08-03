"""Catálogo de produtos vendáveis — Fase 1 do módulo de Produtos/Estoque/Vendas
(plano em /Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Cria `product_categories`, `products`, `product_variants`. Toda venda física
(lanche, bebida, doce...) pendura preço/custo/estoque na VARIANTE, nunca no
produto — um produto "simples" ganha uma variante default "Único" (criada pela
API, não aqui). `tracks_stock` no produto e `cost_avg`/`stock_qty`/`min_stock`
na variante já entram no schema nesta fase (ficam em 0/true sem uso real) para
a Fase 2 (Estoque) não precisar de migration própria para essas colunas — só
para as tabelas de movimentação.

Molde de `commission_transfer.py`/0050: FK CASCADE em `organization_id`, RLS +
FORCE, GRANT explícito ao `barber_app` (aqui incluindo UPDATE, diferente do
0050, pois cadastro é editado com frequência — não só criado/removido).

Revision ID: 0051_product_catalog
Revises: 0050_commission_transfers
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0051_product_catalog"
down_revision = "0050_commission_transfers"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_TABLES = ("product_categories", "products", "product_variants")


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("position", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("organization_id", "name", name="product_categories_org_name_uq"),
    )
    op.create_index(
        "idx_product_categories_org_active", "product_categories", ["organization_id", "active"]
    )

    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "category_id", sa.BigInteger,
            sa.ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=True,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("unit_of_measure", sa.Text, nullable=False, server_default="un"),
        sa.Column("tracks_stock", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_products_org_active", "products", ["organization_id", "active"])
    op.create_index("idx_products_org_category", "products", ["organization_id", "category_id"])

    op.create_table(
        "product_variants",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "product_id", sa.BigInteger,
            sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("sku", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("cost_avg", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("stock_qty", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("min_stock", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("price >= 0", name="product_variants_price_nonneg"),
        sa.CheckConstraint("cost_avg >= 0", name="product_variants_cost_avg_nonneg"),
        sa.CheckConstraint("stock_qty >= 0", name="product_variants_stock_qty_nonneg"),
        sa.CheckConstraint("min_stock >= 0", name="product_variants_min_stock_nonneg"),
        sa.UniqueConstraint("organization_id", "sku", name="product_variants_org_sku_uq"),
    )
    op.create_index(
        "idx_product_variants_org_product", "product_variants", ["organization_id", "product_id"]
    )
    op.create_index(
        "idx_product_variants_org_active", "product_variants", ["organization_id", "active"]
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("product_variants")
    op.drop_table("products")
    op.drop_table("product_categories")
