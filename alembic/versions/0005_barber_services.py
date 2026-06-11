"""barber_services junction table + has_variable_price on services

Revision ID: 0005_barber_services
Revises: 0002_loyalty
Create Date: 2026-06-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_barber_services"
down_revision: Union[str, None] = "0002_loyalty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column(
            "has_variable_price",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "barber_services",
        sa.Column(
            "barber_id",
            sa.BigInteger(),
            sa.ForeignKey("barbers.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "service_id",
            sa.BigInteger(),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    op.create_index("idx_barber_services_service", "barber_services", ["service_id"])


def downgrade() -> None:
    op.drop_index("idx_barber_services_service", table_name="barber_services")
    op.drop_table("barber_services")
    op.drop_column("services", "has_variable_price")
