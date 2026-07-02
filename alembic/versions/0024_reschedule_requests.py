"""pedidos de remarcação de atendimentos (barbeiro → aprovação do gestor)

Revision ID: 0024_reschedule_requests
Revises: 0023_client_debts
Create Date: 2026-07-02

O barbeiro solicita remarcar os próprios atendimentos num período; o pedido fica
`pendente` até um gestor aprovar/recusar (sino na tela do gestor). RLS por
`organization_id` (mesmo padrão de client_debts) + GRANT ao `barber_app`.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0024_reschedule_requests"
down_revision = "0023_client_debts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appointment_reschedule_requests",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "barber_id",
            sa.BigInteger,
            sa.ForeignKey("barbers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("period_start", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("period_end", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pendente'")),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'app'")),
        sa.Column(
            "reviewed_by_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pendente', 'aprovada', 'recusada')",
            name="reschedule_status_valid",
        ),
    )
    op.create_index(
        "idx_reschedule_org_status",
        "appointment_reschedule_requests",
        ["organization_id", "status"],
    )
    op.create_index(
        "idx_reschedule_barber", "appointment_reschedule_requests", ["barber_id"]
    )

    op.execute(
        "ALTER TABLE appointment_reschedule_requests ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON appointment_reschedule_requests "
        "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON appointment_reschedule_requests TO barber_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON appointment_reschedule_requests"
    )
    op.execute(
        "ALTER TABLE appointment_reschedule_requests DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "idx_reschedule_barber", table_name="appointment_reschedule_requests"
    )
    op.drop_index(
        "idx_reschedule_org_status", table_name="appointment_reschedule_requests"
    )
    op.drop_table("appointment_reschedule_requests")
