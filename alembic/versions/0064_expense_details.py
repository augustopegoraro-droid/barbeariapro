"""Despesas ricas + contas a pagar + despesas recorrentes (D-102).

Colunas aditivas em `expenses` (forma de pagamento, subgrupo, beneficiário,
status pago/a_pagar, vencimento, data de pagamento, vínculo de recorrência) +
tabela nova `expense_recurrences` (template que o cron mensal materializa em
1 conta `a_pagar` por mês). Enums PG próprios `expense_method`/`expense_status`.

Molde de `commission_transfers`/0050 e `cash_register`/0063: RLS + FORCE, GRANT
explícito ao `barber_app`. Backfill: adicionar `status` NOT NULL com
`server_default='pago'` carimba toda despesa existente como `pago` — era o que
eram (não havia contas a pagar antes da D-102).

Revision ID: 0064_expense_details
Revises: 0063_cash_register
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0064_expense_details"
down_revision = "0063_cash_register"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_METHODS = (
    "dinheiro",
    "pix",
    "cartao",
    "transferencia",
    "boleto",
    "debito_automatico",
    "outro",
)
_STATUSES = ("pago", "a_pagar")
_SUBGROUP_CHECK = (
    "{col} IS NULL OR {col} IN ('fixa','variavel','pessoal','impostos','outros')"
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_METHODS, name="expense_method").create(bind, checkfirst=False)
    postgresql.ENUM(*_STATUSES, name="expense_status").create(bind, checkfirst=False)

    # ── expense_recurrences (nova) ──────────────────────────────────────────
    op.create_table(
        "expense_recurrences",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            sa.BigInteger,
            sa.ForeignKey("units.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.BigInteger,
            sa.ForeignKey("expense_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "method",
            postgresql.ENUM(*_METHODS, name="expense_method", create_type=False),
            nullable=True,
        ),
        sa.Column("subgroup", sa.Text, nullable=True),
        sa.Column("payee", sa.Text, nullable=True),
        sa.Column("day_of_month", sa.Integer, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("amount >= 0", name="expense_recurrences_amount_nonneg"),
        sa.CheckConstraint(
            "day_of_month BETWEEN 1 AND 28", name="expense_recurrences_day_range"
        ),
        sa.CheckConstraint(
            _SUBGROUP_CHECK.format(col="subgroup"),
            name="expense_recurrences_subgroup_valid",
        ),
    )
    op.create_index(
        "idx_expense_recurrences_org_active",
        "expense_recurrences",
        ["organization_id", "active"],
    )

    op.execute("ALTER TABLE expense_recurrences ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON expense_recurrences "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE expense_recurrences FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT, UPDATE ON expense_recurrences TO barber_app")

    # ── expenses — colunas novas (todas aditivas) ──────────────────────────
    op.add_column(
        "expenses",
        sa.Column(
            "method",
            postgresql.ENUM(*_METHODS, name="expense_method", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("expenses", sa.Column("subgroup", sa.Text, nullable=True))
    op.add_column("expenses", sa.Column("payee", sa.Text, nullable=True))
    op.add_column(
        "expenses",
        sa.Column(
            "status",
            postgresql.ENUM(*_STATUSES, name="expense_status", create_type=False),
            nullable=False,
            server_default="pago",
        ),
    )
    op.add_column("expenses", sa.Column("due_date", sa.Date, nullable=True))
    op.add_column("expenses", sa.Column("paid_at", sa.Date, nullable=True))
    op.add_column("expenses", sa.Column("recurrence_id", sa.BigInteger, nullable=True))
    op.create_foreign_key(
        "expenses_recurrence_id_fkey",
        "expenses",
        "expense_recurrences",
        ["recurrence_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "expenses_subgroup_valid",
        "expenses",
        _SUBGROUP_CHECK.format(col="subgroup"),
    )
    op.create_index(
        "idx_expenses_status_due",
        "expenses",
        ["organization_id", "status", "due_date"],
    )
    op.execute(
        "CREATE UNIQUE INDEX expenses_recurrence_month_unique "
        "ON expenses (organization_id, recurrence_id, competence_month) "
        "WHERE recurrence_id IS NOT NULL"
    )

    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS expenses_recurrence_month_unique")
    op.drop_index("idx_expenses_status_due", table_name="expenses")
    op.drop_constraint("expenses_subgroup_valid", "expenses", type_="check")
    op.drop_constraint("expenses_recurrence_id_fkey", "expenses", type_="foreignkey")
    op.drop_column("expenses", "recurrence_id")
    op.drop_column("expenses", "paid_at")
    op.drop_column("expenses", "due_date")
    op.drop_column("expenses", "status")
    op.drop_column("expenses", "payee")
    op.drop_column("expenses", "subgroup")
    op.drop_column("expenses", "method")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON expense_recurrences")
    op.execute("ALTER TABLE expense_recurrences DISABLE ROW LEVEL SECURITY")
    op.drop_table("expense_recurrences")

    op.execute("DROP TYPE expense_status")
    op.execute("DROP TYPE expense_method")
