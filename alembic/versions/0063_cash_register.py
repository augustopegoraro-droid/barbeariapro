"""Caixa vivo — turno (abrir/fechar em tempo real) + ledger de movimentos (D-101).

Não confundir com `cash_daily_closings` (migration 0026, D-59) — aquela é o
histórico de fechamento diário migrado da Trinks, read-only. Aqui é o caixa
operado ao vivo pela recepção.

- `cash_sessions`: um turno. GRANT SELECT/INSERT/UPDATE (sem DELETE — registro
  financeiro). Índice único parcial garante ≤1 sessão `aberto` por unidade.
- `cash_movements`: ledger **append-only** — GRANT SELECT/INSERT apenas (molde
  `stock_movements`/`audit_logs`). Correção/estorno = novo movimento `ajuste`
  (único tipo que aceita `amount` negativo, via CHECK). Idempotência: índice
  único parcial em `(organization_id, reference_type, reference_id)` para
  `reference_type IN ('payment','sale','expense')`.
- `organizations.cash_register_enforced` (default true): quando true, concluir
  atendimento / vender em DINHEIRO exige um caixa aberto (409).

Molde de `commission_transfers`/0050 e `sales`/0053: RLS + FORCE, GRANT
explícito ao `barber_app`.

Revision ID: 0063_cash_register
Revises: 0062_stripe_connect
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0063_cash_register"
down_revision = "0062_stripe_connect"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_SESSION_STATUSES = ("aberto", "fechado")
_MOVEMENT_TYPES = (
    "venda_servico",
    "venda_produto",
    "suprimento",
    "sangria",
    "despesa",
    "ajuste",
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_SESSION_STATUSES, name="cash_session_status").create(
        bind, checkfirst=False
    )
    postgresql.ENUM(*_MOVEMENT_TYPES, name="cash_movement_type").create(
        bind, checkfirst=False
    )

    op.add_column(
        "organizations",
        sa.Column(
            "cash_register_enforced",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # ── cash_sessions ────────────────────────────────────────────────────────
    op.create_table(
        "cash_sessions",
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
            "status",
            postgresql.ENUM(*_SESSION_STATUSES, name="cash_session_status", create_type=False),
            nullable=False,
            server_default="aberto",
        ),
        sa.Column(
            "opened_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("opened_by_user_id", sa.BigInteger, nullable=True),
        sa.Column("opening_float", sa.Numeric(10, 2), nullable=False),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", sa.BigInteger, nullable=True),
        sa.Column("counted_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("expected_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("difference", sa.Numeric(10, 2), nullable=True),
        sa.Column("closing_note", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("opening_float >= 0", name="cash_sessions_opening_float_nonneg"),
    )
    op.create_index(
        "idx_cash_sessions_org_opened",
        "cash_sessions",
        ["organization_id", "opened_at"],
    )
    op.execute(
        "CREATE UNIQUE INDEX cash_sessions_one_open_per_unit "
        "ON cash_sessions (organization_id, unit_id) WHERE status = 'aberto'"
    )

    op.execute("ALTER TABLE cash_sessions ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON cash_sessions "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE cash_sessions FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT, UPDATE ON cash_sessions TO barber_app")

    # ── cash_movements (append-only) ─────────────────────────────────────────
    op.create_table(
        "cash_movements",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.BigInteger,
            sa.ForeignKey("cash_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "type",
            postgresql.ENUM(*_MOVEMENT_TYPES, name="cash_movement_type", create_type=False),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reference_type", sa.Text, nullable=True),
        sa.Column("reference_id", sa.BigInteger, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "amount >= 0 OR type = 'ajuste'", name="cash_movements_amount_sign"
        ),
    )
    op.create_index(
        "idx_cash_movements_org_session",
        "cash_movements",
        ["organization_id", "session_id", "created_at"],
    )
    op.execute(
        "CREATE UNIQUE INDEX cash_movements_ref_unique "
        "ON cash_movements (organization_id, reference_type, reference_id) "
        "WHERE reference_type IN ('payment', 'sale', 'expense')"
    )

    op.execute("ALTER TABLE cash_movements ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON cash_movements "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE cash_movements FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON cash_movements TO barber_app")

    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON cash_movements")
    op.execute("ALTER TABLE cash_movements DISABLE ROW LEVEL SECURITY")
    op.drop_table("cash_movements")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON cash_sessions")
    op.execute("ALTER TABLE cash_sessions DISABLE ROW LEVEL SECURITY")
    op.drop_table("cash_sessions")
    op.drop_column("organizations", "cash_register_enforced")
    op.execute("DROP TYPE cash_movement_type")
    op.execute("DROP TYPE cash_session_status")
