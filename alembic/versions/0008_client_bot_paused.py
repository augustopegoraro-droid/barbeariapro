"""clients — coluna bot_paused para pausa do bot via CRM

Revision ID: 0008_client_bot_paused
Revises: 0007_crm_leads
Create Date: 2026-06-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_client_bot_paused"
down_revision: Union[str, None] = "0007_crm_leads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column(
            "bot_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("clients", "bot_paused")
