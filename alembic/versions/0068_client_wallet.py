"""Carteira de crédito do cliente final.

`client_wallet_movements` — ledger append-only (molde `MembershipOfferEvent`/
0065, `StockMovement`/0052): saldo = `SUM(amount)`, sem coluna cacheada em
`clients`. GRANT só SELECT/INSERT (sem UPDATE/DELETE — nunca se edita nem se
apaga um movimento; correção é um novo movimento `ajuste` por cima, mesma
lógica de `CashMovement`/`MembershipUsage.reverted_at`).

Revision ID: 0068_client_wallet
Revises: 0067_payment_card_split
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0068_client_wallet"
down_revision = "0067_payment_card_split"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_MOVEMENT_TYPES = ("credito_manual", "uso_pagamento", "estorno", "ajuste")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_MOVEMENT_TYPES, name="client_wallet_movement_type").create(
        bind, checkfirst=False
    )

    op.create_table(
        "client_wallet_movements",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "client_id", sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "movement_type",
            postgresql.ENUM(*_MOVEMENT_TYPES, name="client_wallet_movement_type", create_type=False),
            nullable=False,
        ),
        sa.Column("reference_type", sa.Text(), nullable=True),
        sa.Column("reference_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("amount <> 0", name="client_wallet_movements_amount_nonzero"),
    )
    op.create_index(
        "idx_client_wallet_movements_org_client",
        "client_wallet_movements",
        ["organization_id", "client_id", "created_at"],
    )

    op.execute("ALTER TABLE client_wallet_movements ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON client_wallet_movements "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE client_wallet_movements FORCE ROW LEVEL SECURITY")

    op.execute("GRANT SELECT, INSERT ON client_wallet_movements TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON client_wallet_movements")
    op.execute("ALTER TABLE client_wallet_movements DISABLE ROW LEVEL SECURITY")
    op.drop_table("client_wallet_movements")
    op.execute("DROP TYPE IF EXISTS client_wallet_movement_type")
