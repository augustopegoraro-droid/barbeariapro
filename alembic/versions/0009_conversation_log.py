"""message_log — body_text para histórico de conversa WhatsApp

Revision ID: 0009_conversation_log
Revises: 0008_client_bot_paused
Create Date: 2026-06-23

Aditiva: adiciona body_text à tabela message_log existente, permitindo gravar
o texto de cada mensagem trocada entre cliente e bot. Sem impacto em registros
existentes (nullable).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_conversation_log"
down_revision: Union[str, None] = "0008_client_bot_paused"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "message_log",
        sa.Column("body_text", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("message_log", "body_text")
