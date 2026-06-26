"""Webhook direto da Evolution API para ingestão de mensagens sem delay.

Fluxo:
  Evolution → POST /bot/wa-webhook → record_message (imediato) + SSE
                                   → forward n8n (background, retry 3x)

Substitui o caminho: Evolution → n8n (5s debounce) → /bot/log
para o registro no CRM. O n8n continua recebendo o payload via forward
para que o bot IA continue funcionando normalmente.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import secrets_match
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import conversation as conv_svc
from app.services.conversation import MediaIn
from models.enums import AttachmentMediaType, MessageSenderType, MessageType

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bot", tags=["webhook"])

_MSG_TYPE_MAP: dict[str, MessageType] = {
    "conversation": MessageType.text,
    "extendedTextMessage": MessageType.text,
    "audioMessage": MessageType.audio,
    "imageMessage": MessageType.image,
    "documentMessage": MessageType.document,
    "videoMessage": MessageType.document,
}


async def _get_webhook_db(
    x_webhook_secret: Annotated[Optional[str], Header(alias="X-Webhook-Secret")] = None,
) -> AsyncIterator[AsyncSession]:
    """Sessão DB para o webhook da Evolution. Valida X-Webhook-Secret se configurado.

    Comparação em tempo constante. Enquanto WA_WEBHOOK_SECRET estiver vazio o
    header é opcional (comportamento atual de produção). Tornar obrigatório
    exige antes provisionar o segredo na Evolution e no .env da VM (Fase 1.4).
    """
    if settings.wa_webhook_secret and not secrets_match(x_webhook_secret, settings.wa_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook secret inválido")
    if not settings.bot_organization_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="BOT_ORGANIZATION_ID não configurado")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, settings.bot_organization_id)
            yield session


def _extract_phone(remote_jid: str) -> Optional[str]:
    """Retorna E.164 a partir do remoteJid, ou None se não for individual."""
    if "@s.whatsapp.net" not in remote_jid:
        return None
    digits = "".join(c for c in remote_jid.split("@")[0] if c.isdigit())
    return f"+{digits}" if digits else None


def _extract_content(
    msg_type: str, message: dict
) -> tuple[Optional[str], Optional[MediaIn]]:
    """Extrai (body, MediaIn) do campo `data.message` do payload Evolution."""
    if msg_type == "conversation":
        return message.get("conversation"), None

    if msg_type == "extendedTextMessage":
        inner = message.get("extendedTextMessage", {})
        return inner.get("text"), None

    if msg_type == "audioMessage":
        inner = message.get("audioMessage", {})
        return None, MediaIn(
            media_type=AttachmentMediaType.audio,
            url=inner.get("url"),
            mime=inner.get("mimetype"),
            duration_s=inner.get("seconds"),
        )

    if msg_type == "imageMessage":
        inner = message.get("imageMessage", {})
        caption = inner.get("caption")
        return caption, MediaIn(
            media_type=AttachmentMediaType.image,
            url=inner.get("url"),
            mime=inner.get("mimetype"),
            caption=caption,
        )

    if msg_type in ("documentMessage", "videoMessage"):
        inner = message.get(msg_type, {})
        label = inner.get("fileName") or inner.get("title")
        media_t = AttachmentMediaType.document if msg_type == "documentMessage" else AttachmentMediaType.video
        return label, MediaIn(
            media_type=media_t,
            url=inner.get("url"),
            mime=inner.get("mimetype"),
            caption=label,
        )

    return None, None


async def _forward_to_n8n(payload: dict, attempt: int = 1) -> None:
    """Encaminha payload original ao n8n com exponential backoff (máx 3 tentativas)."""
    if not settings.n8n_webhook_url:
        return
    url = f"{settings.n8n_webhook_url.rstrip('/')}/webhook/whatsapp"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            _logger.debug("wa_webhook forward n8n ok attempt=%d", attempt)
    except Exception as exc:
        if attempt < 3:
            await asyncio.sleep(2 ** (attempt - 1))
            await _forward_to_n8n(payload, attempt + 1)
        else:
            _logger.error("wa_webhook forward n8n FALHOU após %d tentativas: %s", attempt, exc)


@router.post("/wa-webhook", status_code=200)
async def evolution_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(_get_webhook_db)],
) -> dict:
    """Recebe webhook da Evolution API e registra mensagens sem o delay do n8n.

    1. Encaminha payload ao n8n em background (bot continua funcionando).
    2. Registra mensagem inbound imediatamente → SSE para o Inbox.
    """
    payload: dict = await request.json()
    event: str = payload.get("event", "")
    _logger.debug(
        "wa_webhook recebido event=%r instance=%r data_keys=%s",
        event, payload.get("instance"), list(payload.get("data", {}).keys()),
    )

    # Não encaminha send.message ao n8n para evitar loop (bot responde, n8n recebe, gera outra resposta...)
    if event != "send.message":
        background_tasks.add_task(_forward_to_n8n, payload)

    _MSG_EVENTS = ("messages.upsert", "send.message")
    if event not in _MSG_EVENTS:
        return {"ok": True, "skipped": True, "reason": f"event={event}"}

    data: dict = payload.get("data", {})
    key: dict = data.get("key", {})

    # send.message é sempre fromMe=true; messages.upsert depende do campo
    from_me: bool = (event == "send.message") or key.get("fromMe", False)

    # Filtra apenas mensagens de contatos individuais
    phone = _extract_phone(key.get("remoteJid", ""))
    if phone is None:
        return {"ok": True, "skipped": True, "reason": "not_individual"}

    # Valida instância se configurada
    instance = payload.get("instance", "")
    if settings.evolution_instance_name and instance != settings.evolution_instance_name:
        _logger.warning("wa_webhook instance inesperada: got=%r expected=%r", instance, settings.evolution_instance_name)
        return {"ok": True, "skipped": True, "reason": "instance_mismatch"}

    sender_type = MessageSenderType.bot if from_me else MessageSenderType.client
    _logger.info("wa_webhook event=%s phone=%s sender=%s", event, phone, sender_type.value)

    wa_message_id: Optional[str] = key.get("id")
    msg_type_raw: str = data.get("messageType", "conversation")
    crm_msg_type = _MSG_TYPE_MAP.get(msg_type_raw, MessageType.text)
    message_dict: dict = data.get("message", {})
    body, media = _extract_content(msg_type_raw, message_dict)

    try:
        await conv_svc.record_message(
            db,
            org_id=settings.bot_organization_id,
            phone=phone,
            sender_type=sender_type,
            body=body,
            message_type=crm_msg_type,
            wa_message_id=wa_message_id,
            media=media,
        )
        await db.commit()
    except Exception as exc:
        _logger.error("wa_webhook record_message falhou phone=%s: %s", phone, exc)
        await db.rollback()

    return {"ok": True}
