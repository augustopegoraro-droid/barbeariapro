"""linhas mensais do DRE (histórico financeiro migrado da Trinks)

Revision ID: 0036_dre_monthly_lines
Revises: 0035_payment_transactions
Create Date: 2026-07-06

Histórico do "DRE" (Demonstrativo de Resultado) mensal da Trinks: uma linha por
item-folha por mês (receita por tipo + despesa por categoria/subgrupo). Guarda só
as linhas-folha — subtotais/totais do arquivo são recomputados (sem dupla
contagem). É por COMPETÊNCIA, complementar (não reconciliável 1:1) a
`payment_transactions`/`cash_daily_closings` (recebimento).

Mesmo molde de `payment_transactions` (0035): FK CASCADE + RLS por
`organization_id` + GRANT ao `barber_app`. CHECK só em `section` (receita|despesa);
sem CHECK de sinal em `amount` — contra-receitas são legitimamente negativas. O
importador é idempotente por substituição dos meses cobertos pelo arquivo, então
sem UNIQUE (um arquivo é a fonte da verdade do mês; re-rodar substitui).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0036_dre_monthly_lines"
down_revision = "0035_payment_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dre_monthly_lines",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("competence_month", sa.Date, nullable=False),
        sa.Column("section", sa.Text, nullable=False),
        sa.Column("subgroup", sa.Text, nullable=True),
        sa.Column("line_item", sa.Text, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'trinks'")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "section IN ('receita', 'despesa')", name="dre_section_valid"
        ),
    )
    op.create_index(
        "idx_dre_monthly_lines_org_month",
        "dre_monthly_lines",
        ["organization_id", "competence_month"],
    )

    op.execute("ALTER TABLE dre_monthly_lines ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON dre_monthly_lines "
        "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON dre_monthly_lines TO barber_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dre_monthly_lines")
    op.execute("ALTER TABLE dre_monthly_lines DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_dre_monthly_lines_org_month", table_name="dre_monthly_lines")
    op.drop_table("dre_monthly_lines")
