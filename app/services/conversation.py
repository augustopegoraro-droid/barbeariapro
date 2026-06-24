"""Captura unificada da conversa WhatsApp (texto + mídia + sistema).

Única porta de escrita de `messages`. Idempotente por (conversation, wamid, sender).
Não altera estágio de lead — isso permanece em app/api/bot.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import Attachment, Conversation, Lead, Message
from models.enums import (AttachmentMediaType, ContactChannel, MessageSenderType,
                          MessageType)

_logger = logging.getLogger(__name__)
_PREVIEW = {MessageType.audio: "🎤 Áudio", MessageType.image: "📷 Imagem",
            MessageType.document: "📎 Documento"}


@dataclass
class MediaIn:
    media_type: AttachmentMediaType
    url: Optional[str] = None
    mime: Optional[str] = None
    size_bytes: Optional[int] = None
    duration_s: Optional[int] = None
    transcript: Optional[str] = None
    caption: Optional[str] = None


async def get_or_create_conversation(
    db: AsyncSession, org_id: int, phone: str, *,
    client_id: Optional[int] = None,
    channel: ContactChannel = ContactChannel.whatsapp,
) -> Conversation:
    """Upsert atômico por (org, phone, channel). Resolve 1º contato sem cliente."""
    stmt = (
        pg_insert(Conversation)
        .values(organization_id=org_id, phone_e164=phone, channel=channel,
                client_id=client_id)
        .on_conflict_do_nothing(constraint="conversations_phone_per_org")
    )
    await db.execute(stmt)

    conv = (
        await db.execute(
            select(Conversation)
            .where(Conversation.organization_id == org_id,
                   Conversation.phone_e164 == phone,
                   Conversation.channel == channel))
    ).scalar_one()

    if client_id and conv.client_id is None:
        conv.client_id = client_id

    if conv.lead_id is None:
        if client_id:
            lead_q = select(Lead).where(Lead.client_id == client_id)
        else:
            lead_q = (
                select(Lead)
                .where(Lead.phone_e164 == phone, Lead.organization_id == org_id)
                .order_by(Lead.id.desc())
                .limit(1)
            )
        lead = (await db.execute(lead_q)).scalars().first()
        if lead:
            conv.lead_id = lead.id

    return conv


async def record_message(
    db: AsyncSession, *,
    org_id: int,
    phone: str,
    sender_type: MessageSenderType,
    body: Optional[str],
    message_type: MessageType = MessageType.text,
    wa_message_id: Optional[str] = None,
    sender_user_id: Optional[int] = None,
    client_id: Optional[int] = None,
    media: Optional[MediaIn] = None,
    message_log_id: Optional[int] = None,
) -> Optional[Message]:
    """Grava uma mensagem (idempotente). Retorna None se for duplicata."""
    conv = await get_or_create_conversation(db, org_id, phone, client_id=client_id)

    if wa_message_id:
        dup = (await db.execute(
            select(Message.id).where(
                Message.conversation_id == conv.id,
                Message.wa_message_id == wa_message_id,
                Message.sender_type == sender_type)
        )).scalar_one_or_none()
        if dup is not None:
            _logger.info("message duplicate conv=%s wamid=%s", conv.id, wa_message_id)
            return None

    msg = Message(
        organization_id=org_id,
        conversation_id=conv.id,
        sender_type=sender_type,
        sender_user_id=sender_user_id,
        message_type=message_type,
        body_text=body,
        wa_message_id=wa_message_id,
        message_log_id=message_log_id,
        created_at=datetime.now(timezone.utc),  # explícito: server_default não popula após flush()
    )
    db.add(msg)
    await db.flush()

    if media is not None:
        db.add(Attachment(
            organization_id=org_id,
            message_id=msg.id,
            media_type=media.media_type,
            url=media.url,
            mime=media.mime,
            size_bytes=media.size_bytes,
            duration_s=media.duration_s,
            transcript=media.transcript,
            caption=media.caption,
        ))

    now = datetime.now(timezone.utc)
    conv.last_message_at = now
    conv.updated_at = now
    conv.last_message_preview = (
        (body or "")[:120] if message_type == MessageType.text
        else _PREVIEW.get(message_type, "")
    )
    if sender_type == MessageSenderType.client:
        conv.unread_count = (conv.unread_count or 0) + 1

    await _publish(org_id, conv.id, msg)
    return msg


async def _publish(org_id: int, conversation_id: int, msg: Message) -> None:
    """Publica evento SSE. Chamado após flush (msg.id garantido), antes do commit.

    O payload traz a mensagem completa — o frontend a adiciona ao estado local
    sem precisar de um GET adicional, eliminando a janela de race condition.
    """
    from app.services import sse_broker

    event = {
        "type": "new_message",
        "conversation_id": conversation_id,
        "message": {
            "id": msg.id,
            "sender_type": msg.sender_type.value,
            "message_type": msg.message_type.value,
            "body": msg.body_text,
            "wa_message_id": msg.wa_message_id,
            "created_at": (msg.created_at or datetime.now(timezone.utc)).isoformat(),
            "attachments": [],
        },
    }
    await sse_broker.publish(org_id, event)
