"""grant permissões de CRUD ao barber_app nas tabelas CRM

Revision ID: 0011_grant_crm_tables
Revises: 0010_conversations
Create Date: 2026-06-24

A migration 0010 criou conversations/messages/attachments mas omitiu o GRANT
para o role barber_app. Sem ele, qualquer operação de escrita/leitura pelo
app falha com InsufficientPrivilege (RLS nunca chega a ser avaliado).
"""
from __future__ import annotations

from alembic import op

revision = "0011_grant_crm_tables"
down_revision = "0010_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE
        ON conversations, messages, attachments
        TO barber_app
    """)
    op.execute("""
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app
    """)


def downgrade() -> None:
    op.execute("""
        REVOKE SELECT, INSERT, UPDATE, DELETE
        ON conversations, messages, attachments
        FROM barber_app
    """)
