"""Avaliação pós-atendimento pelo cliente final (Fase A do app nativo).

Molde de `commission_transfers`/0050 e `push_subscriptions`/0056 (RLS +
`FORCE ROW LEVEL SECURITY` + GRANT explícito ao `barber_app`), com uma
diferença deliberada: o GRANT é **só `SELECT, INSERT`**.

A avaliação é **definitiva** — não existe endpoint de edição nem de remoção,
e o banco é o backstop disso (mesma lógica de `audit_logs`/`stock_movements`).
Uma avaliação por atendimento (UNIQUE em `appointment_id`).

`barber_id` é denormalizado (ON DELETE SET NULL) para que médias por
profissional saiam sem join com `appointment_items` e sem migration nova.

Revision ID: 0058_appointment_ratings
Revises: 0057_product_purchase_requests
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0058_appointment_ratings"
down_revision = "0057_product_purchase_requests"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    op.create_table(
        "appointment_ratings",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "appointment_id", sa.BigInteger,
            sa.ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "client_id", sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "barber_id", sa.BigInteger,
            sa.ForeignKey("barbers.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="appointment_ratings_rating_range"),
        sa.CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 1000",
            name="appointment_ratings_comment_len",
        ),
        sa.UniqueConstraint("appointment_id", name="appointment_ratings_appointment_uq"),
    )
    op.create_index(
        "idx_appointment_ratings_org_barber",
        "appointment_ratings",
        ["organization_id", "barber_id"],
    )

    op.execute("ALTER TABLE appointment_ratings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON appointment_ratings "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE appointment_ratings FORCE ROW LEVEL SECURITY")
    # Append-only de propósito: sem UPDATE/DELETE (avaliação é definitiva).
    op.execute("GRANT SELECT, INSERT ON appointment_ratings TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON appointment_ratings")
    op.execute("ALTER TABLE appointment_ratings DISABLE ROW LEVEL SECURITY")
    op.drop_table("appointment_ratings")
