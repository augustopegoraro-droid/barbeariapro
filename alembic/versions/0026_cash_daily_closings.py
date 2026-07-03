"""fechamento de caixa diário (migração histórica da Trinks)

Revision ID: 0026_cash_daily_closings
Revises: 0025_barber_work_model
Create Date: 2026-07-02

Histórico do "Resumo de Movimentação de Entradas e Saídas" da Trinks: um
fechamento por dia (abertura/recebido/troco/despesas/sangria/saldo). Ainda não
existe módulo de Caixa (abrir/fechar em tempo real) no sistema — esta tabela só
guarda o histórico migrado para consulta/relatório, no mesmo molde de
`client_debts` (0023): FK CASCADE + RLS por `organization_id` + GRANT ao
`barber_app`. `UNIQUE(organization_id, closing_date)` garante idempotência do
importador (upsert por dia, sem duplicar em re-importações).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0026_cash_daily_closings"
down_revision = "0025_barber_work_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cash_daily_closings",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("closing_date", sa.Date, nullable=False),
        sa.Column("opening_balance", sa.Numeric(10, 2), nullable=False),
        sa.Column("cash_received", sa.Numeric(10, 2), nullable=False),
        sa.Column("change_given", sa.Numeric(10, 2), nullable=False),
        sa.Column("cash_expenses", sa.Numeric(10, 2), nullable=False),
        sa.Column("cash_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("withdrawal", sa.Numeric(10, 2), nullable=False),
        sa.Column("closing_balance", sa.Numeric(10, 2), nullable=False),
        sa.Column("other_methods_received", sa.Numeric(10, 2), nullable=False),
        sa.Column("other_methods_expenses", sa.Numeric(10, 2), nullable=False),
        sa.Column("opening_history", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'trinks'")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "organization_id", "closing_date", name="cash_daily_closings_org_date_unique"
        ),
    )
    op.create_index(
        "idx_cash_daily_closings_org_date",
        "cash_daily_closings",
        ["organization_id", "closing_date"],
    )

    op.execute("ALTER TABLE cash_daily_closings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON cash_daily_closings "
        "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON cash_daily_closings TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON cash_daily_closings")
    op.execute("ALTER TABLE cash_daily_closings DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_cash_daily_closings_org_date", table_name="cash_daily_closings")
    op.drop_table("cash_daily_closings")
