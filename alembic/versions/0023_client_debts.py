"""contas a receber: débitos de clientes (migração da Trinks)

Revision ID: 0023_client_debts
Revises: 0022_client_trinks_fields
Create Date: 2026-07-02

Débito = valor que o cliente deve (agendamento não pago / fechamento com dívida).
Não cabia em `payments` (que exige appointment e representa dinheiro recebido), então
ganha tabela própria de contas a receber. `client_id` é NULLABLE porque o export da
Trinks casa o cliente só por NOME (pode não achar) — nesse caso guardamos `client_name`
para não perder o débito.

RLS por `organization_id` (mesmo padrão das demais) + GRANT ao `barber_app`.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0023_client_debts"
down_revision = "0022_client_trinks_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_debts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("client_name", sa.Text, nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("debt_date", sa.Date, nullable=True),
        sa.Column("service_desc", sa.Text, nullable=True),
        sa.Column("professional", sa.Text, nullable=True),
        # 'agendamento_nao_pago' | 'fechamento_com_divida' | outro (texto livre da Trinks)
        sa.Column("kind", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'aberto'")),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'trinks'")),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("amount >= 0", name="client_debts_amount_nonneg"),
        sa.CheckConstraint(
            "status IN ('aberto', 'pago')", name="client_debts_status_valid"
        ),
    )
    op.create_index(
        "idx_client_debts_org_status",
        "client_debts",
        ["organization_id", "status"],
    )
    op.create_index("idx_client_debts_client", "client_debts", ["client_id"])

    op.execute("ALTER TABLE client_debts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON client_debts "
        "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON client_debts TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON client_debts")
    op.execute("ALTER TABLE client_debts DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_client_debts_client", table_name="client_debts")
    op.drop_index("idx_client_debts_org_status", table_name="client_debts")
    op.drop_table("client_debts")
