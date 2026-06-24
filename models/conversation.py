"""CRM conversacional: conversations, messages, attachments.

Aditivo e isolado por organização (RLS tenant_isolation). Não altera message_log.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (BigInteger, Boolean, ForeignKey, Identity, Index, Integer,
                        Text, TIMESTAMP, UniqueConstraint, func, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (AttachmentMediaType, ContactChannel, ConversationStatus,
                    MessageSenderType, MessageType, pg_enum)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("organization_id", "phone_e164", "channel",
                         name="conversations_phone_per_org"),
        Index("idx_conversations_list", "organization_id", "status",
              text("last_message_at DESC")),
        Index("idx_conversations_client", "client_id"),
        Index("idx_conversations_lead", "lead_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="SET NULL"))
    lead_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="SET NULL"))
    assigned_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[ContactChannel] = mapped_column(
        pg_enum(ContactChannel, "contact_channel"), nullable=False,
        server_default=text("'whatsapp'"))
    status: Mapped[ConversationStatus] = mapped_column(
        pg_enum(ConversationStatus, "conversation_status"), nullable=False,
        server_default=text("'open'"))
    bot_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             server_default=text("true"))
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                              server_default=text("0"))
    last_message_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    last_message_preview: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_conv_created", "conversation_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_type: Mapped[MessageSenderType] = mapped_column(
        pg_enum(MessageSenderType, "message_sender_type"), nullable=False)
    sender_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    message_type: Mapped[MessageType] = mapped_column(
        pg_enum(MessageType, "message_type"), nullable=False,
        server_default=text("'text'"))
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    wa_message_id: Mapped[Optional[str]] = mapped_column(Text)
    message_log_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("message_log.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    attachments: Mapped[List["Attachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan")


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (Index("idx_attachments_message", "message_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    media_type: Mapped[AttachmentMediaType] = mapped_column(
        pg_enum(AttachmentMediaType, "attachment_media_type"), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text)
    mime: Mapped[Optional[str]] = mapped_column(Text)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    duration_s: Mapped[Optional[int]] = mapped_column(Integer)
    transcript: Mapped[Optional[str]] = mapped_column(Text)
    caption: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    message: Mapped["Message"] = relationship(back_populates="attachments")
