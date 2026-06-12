"""add is_blocked to clients

Revision ID: 0006_client_blocked
Revises: 0005_barber_services
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0006_client_blocked"
down_revision = "0005_barber_services"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("clients", "is_blocked")
