"""Repasse de comissão entre barbeiros (D-88).

Cria `commission_transfers`: lançamento vinculado a um `AppointmentItem` já
concluído em que uma fração da comissão (`price_charged × Barber.
commission_pct`) é repassada a OUTRO barbeiro (atendimento a 4 mãos, acordo
entre profissionais). Não mexe em `AppointmentItem.barber_id` nem em
`Barber.commission_pct` — é uma correção lançada por cima, aplicada em
`management.py::commission_transfer_deltas` na hora de agregar comissão por
período (o total pago não muda, só a distribuição entre os dois barbeiros).

`amount` é snapshot do valor calculado no momento do lançamento (a história
não muda se o `commission_pct` do barbeiro for editado depois). Molde de
`consent_records` (0042): FK CASCADE em `organization_id`, RLS + FORCE, GRANT
explícito ao `barber_app`. `created_by_user_id` sem FK, mesma lógica do D-86/
0048 (fato histórico, não trava se o usuário for removido).

Revision ID: 0050_commission_transfers
Revises: 0049_legal_acceptance
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0050_commission_transfers"
down_revision = "0049_legal_acceptance"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    op.create_table(
        "commission_transfers",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "appointment_item_id",
            sa.BigInteger,
            sa.ForeignKey("appointment_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "from_barber_id",
            sa.BigInteger,
            sa.ForeignKey("barbers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "to_barber_id",
            sa.BigInteger,
            sa.ForeignKey("barbers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pct", sa.Numeric(5, 4), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("pct > 0 AND pct <= 1", name="commission_transfers_pct_range"),
        sa.CheckConstraint("amount >= 0", name="commission_transfers_amount_nonneg"),
        sa.CheckConstraint(
            "from_barber_id <> to_barber_id", name="commission_transfers_distinct_barbers"
        ),
    )
    op.create_index(
        "idx_commission_transfers_org_item",
        "commission_transfers",
        ["organization_id", "appointment_item_id"],
    )
    op.create_index(
        "idx_commission_transfers_org_to",
        "commission_transfers",
        ["organization_id", "to_barber_id", "created_at"],
    )

    op.execute("ALTER TABLE commission_transfers ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON commission_transfers "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE commission_transfers FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT, DELETE ON commission_transfers TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON commission_transfers")
    op.execute("ALTER TABLE commission_transfers DISABLE ROW LEVEL SECURITY")
    op.drop_table("commission_transfers")
