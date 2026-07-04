"""transações de pagamento (histórico analítico migrado da Trinks)

Revision ID: 0035_payment_transactions
Revises: 0034_platform_audit_log
Create Date: 2026-07-03

Histórico do relatório "Pagamentos/Estornos" da Trinks: um registro por
pagamento/troco por comanda (tipo/forma de pagamento, valor, taxa da operadora,
líquido a receber, conta financeira). Não existe módulo de conciliação vivo — esta
tabela guarda o histórico migrado para relatórios de mix de formas de pagamento,
custo de cartão e recebíveis, no mesmo molde de `cash_daily_closings` (0026): FK
CASCADE + RLS por `organization_id` + GRANT ao `barber_app`.

O importador é idempotente por substituição de período (delete + insert do
intervalo de `movement_date` coberto pelo arquivo), então esta migration não impõe
UNIQUE (as linhas não têm chave natural única — pode haver pagamentos idênticos no
mesmo dia). Sem CHECK de sinal: o espelho preserva valores negativos legítimos
(desconto de operadora, troco).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0035_payment_transactions"
down_revision = "0034_platform_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("movement_date", sa.Date, nullable=False),
        sa.Column("service_date", sa.Date, nullable=True),
        sa.Column("expected_receipt_date", sa.Date, nullable=True),
        sa.Column("payment_type", sa.Text, nullable=False),
        sa.Column("payment_method", sa.Text, nullable=False),
        sa.Column("installment", sa.Text, nullable=True),
        sa.Column(
            "anticipated", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "entry_type",
            sa.Text,
            nullable=False,
            server_default=sa.text("'Pagamento'"),
        ),
        sa.Column("comanda", sa.Text, nullable=True),
        sa.Column("amount_paid", sa.Numeric(12, 2), nullable=False),
        sa.Column("operator_discount_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "operator_discount_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("amount_to_receive", sa.Numeric(12, 2), nullable=False),
        sa.Column("account", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'trinks'")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_payment_transactions_org_date",
        "payment_transactions",
        ["organization_id", "movement_date"],
    )

    op.execute("ALTER TABLE payment_transactions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON payment_transactions "
        "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON payment_transactions TO barber_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payment_transactions")
    op.execute("ALTER TABLE payment_transactions DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "idx_payment_transactions_org_date", table_name="payment_transactions"
    )
    op.drop_table("payment_transactions")
