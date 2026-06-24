"""crm conversacional — conversations + messages + attachments (+ enums)

Revision ID: 0010_conversations
Revises: 0009_conversation_log
Create Date: 2026-06-24

Aditiva: cria tabelas/enums novos para a conversa do WhatsApp. NÃO altera
message_log, leads, lead_events nem clients.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_conversations"
down_revision: Union[str, None] = "0009_conversation_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONV_STATUS = ("open", "snoozed", "closed")
_SENDER = ("client", "bot", "human", "system")
_MSG_TYPE = ("text", "audio", "image", "document", "event")
_MEDIA = ("audio", "image", "document", "video")


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _contact_channel() -> postgresql.ENUM:
    return postgresql.ENUM(name="contact_channel", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(*_CONV_STATUS, name="conversation_status").create(bind, checkfirst=False)
    postgresql.ENUM(*_SENDER, name="message_sender_type").create(bind, checkfirst=False)
    postgresql.ENUM(*_MSG_TYPE, name="message_type").create(bind, checkfirst=False)
    postgresql.ENUM(*_MEDIA, name="attachment_media_type").create(bind, checkfirst=False)

    # ── conversations ──────────────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger,
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.BigInteger,
                  sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lead_id", sa.BigInteger,
                  sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_user_id", sa.BigInteger,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("phone_e164", sa.Text, nullable=False),
        sa.Column("channel", _contact_channel(), nullable=False,
                  server_default=sa.text("'whatsapp'")),
        sa.Column("status", _enum("conversation_status"), nullable=False,
                  server_default=sa.text("'open'")),
        sa.Column("bot_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("unread_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_message_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "phone_e164", "channel",
                            name="conversations_phone_per_org"),
    )
    op.create_index("idx_conversations_list", "conversations",
                    ["organization_id", "status", sa.text("last_message_at DESC")])
    op.create_index("idx_conversations_client", "conversations", ["client_id"])
    op.create_index("idx_conversations_lead", "conversations", ["lead_id"])

    # ── messages ───────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger,
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("conversation_id", sa.BigInteger,
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_type", _enum("message_sender_type"), nullable=False),
        sa.Column("sender_user_id", sa.BigInteger,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_type", _enum("message_type"), nullable=False,
                  server_default=sa.text("'text'")),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("wa_message_id", sa.Text, nullable=True),
        sa.Column("message_log_id", sa.BigInteger,
                  sa.ForeignKey("message_log.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_messages_conv_created", "messages",
                    ["conversation_id", "created_at", "id"])
    op.create_index("uq_messages_wamid", "messages",
                    ["conversation_id", "wa_message_id", "sender_type"],
                    unique=True, postgresql_where=sa.text("wa_message_id IS NOT NULL"))
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX idx_messages_body_trgm ON messages "
               "USING gin (body_text gin_trgm_ops)")

    # ── attachments ────────────────────────────────────────────────────────
    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger,
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("message_id", sa.BigInteger,
                  sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_type", _enum("attachment_media_type"), nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("mime", sa.Text, nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("duration_s", sa.Integer, nullable=True),
        sa.Column("transcript", sa.Text, nullable=True),
        sa.Column("caption", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_attachments_message", "attachments", ["message_id"])

    # ── RLS — mesmo padrão das demais tabelas tenant ───────────────────────
    for tbl in ("conversations", "messages", "attachments"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tbl} "
            "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
        )

    # ── backfill do histórico já em message_log.body_text ─────────────────
    op.execute("""
        INSERT INTO conversations (organization_id, client_id, phone_e164, channel,
                                   status, last_message_at, last_message_preview)
        SELECT c.organization_id, c.id, c.phone_e164, 'whatsapp', 'open',
               max(m.created_at),
               left((array_agg(m.body_text ORDER BY m.created_at DESC))[1], 120)
        FROM message_log m JOIN clients c ON c.id = m.client_id
        WHERE m.body_text IS NOT NULL
        GROUP BY c.organization_id, c.id, c.phone_e164
        ON CONFLICT (organization_id, phone_e164, channel) DO NOTHING
    """)
    op.execute("""
        INSERT INTO messages (organization_id, conversation_id, sender_type,
                              message_type, body_text, created_at)
        SELECT m.organization_id, conv.id,
               CASE WHEN m.direction = 'inbound' THEN 'client'::message_sender_type
                    ELSE 'bot'::message_sender_type END,
               'text'::message_type, m.body_text, m.created_at
        FROM message_log m
        JOIN clients c ON c.id = m.client_id
        JOIN conversations conv
          ON conv.organization_id = c.organization_id
         AND conv.phone_e164 = c.phone_e164 AND conv.channel = 'whatsapp'
        WHERE m.body_text IS NOT NULL
    """)


def downgrade() -> None:
    bind = op.get_bind()
    for tbl in ("attachments", "messages", "conversations"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_messages_body_trgm")
    op.drop_table("attachments")
    op.drop_table("messages")
    op.drop_table("conversations")
    for name in ("attachment_media_type", "message_type",
                 "message_sender_type", "conversation_status"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
