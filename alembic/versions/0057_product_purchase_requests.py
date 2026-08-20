"""Sugestão de compra de produto (barbeiro/recepção → aprovação do gestor) — D-98.

Estende o padrão de `appointment_reschedule_requests` (0024) para um novo caso
de "solicitação pendente de aprovação": quem opera o dia a dia (barbeiro,
recepção) nota estoque baixo e SUGERE a compra, sem executá-la — só
owner/manager (`purchases.manage`) compra de fato (D-93). É uma sugestão
informal, diferente do pedido de compra formal (`purchase_orders`); se
aprovada, pode (opcionalmente) virar um `purchase_order` — daí a FK nullable
`purchase_order_id`, que nasce agora para não exigir migration nova quando o
gestor materializar a sugestão.

Alvo do pedido é `variant_id` (quando quem pediu conhece a variação) OU
`product_name` (texto livre — o barbeiro pelo Kernel IA não conhece IDs);
pelo menos um dos dois é exigido (CHECK). RLS + FORCE no molde de
`commission_transfers` (0050) — mais forte que a 0024, que não tinha FORCE.

Revision ID: 0057_product_purchase_requests
Revises: 0056_push_notifications
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0057_product_purchase_requests"
down_revision = "0056_push_notifications"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    op.create_table(
        "product_purchase_requests",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.BigInteger,
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("product_name", sa.Text, nullable=True),
        sa.Column("qty_suggested", sa.Numeric(12, 3), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pendente'")),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'app'")),
        sa.Column(
            "requested_by_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.Column(
            "purchase_order_id",
            sa.BigInteger,
            sa.ForeignKey("purchase_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pendente', 'aprovada', 'recusada')",
            name="purchase_request_status_valid",
        ),
        sa.CheckConstraint(
            "source IN ('app', 'kernel_ia')",
            name="purchase_request_source_valid",
        ),
        sa.CheckConstraint(
            "qty_suggested IS NULL OR qty_suggested > 0",
            name="purchase_request_qty_positive",
        ),
        sa.CheckConstraint(
            "variant_id IS NOT NULL OR product_name IS NOT NULL",
            name="purchase_request_target_present",
        ),
    )
    op.create_index(
        "idx_purchase_requests_org_status",
        "product_purchase_requests",
        ["organization_id", "status"],
    )
    op.create_index(
        "idx_purchase_requests_org_variant",
        "product_purchase_requests",
        ["organization_id", "variant_id"],
    )

    op.execute("ALTER TABLE product_purchase_requests ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON product_purchase_requests "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE product_purchase_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON product_purchase_requests TO barber_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON product_purchase_requests")
    op.execute("ALTER TABLE product_purchase_requests DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_purchase_requests_org_variant", table_name="product_purchase_requests")
    op.drop_index("idx_purchase_requests_org_status", table_name="product_purchase_requests")
    op.drop_table("product_purchase_requests")
