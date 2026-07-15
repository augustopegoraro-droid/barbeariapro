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
from app.core.phone import mask_phone
from app.core.security import secrets_match
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import conversation as conv_svc
from app.services import opt_out as opt_out_svc
from app.services.conversation import MediaIn
from app.services.tenant import org_id_by_wa_instance
from app.services.whatsapp import send_text
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

    A sessão é aberta SEM tenant: o `org_id` é resolvido pela instância do payload
    dentro do handler (multi-tenant), e o `set_current_org` é feito lá antes de
    qualquer query escopada.
    """
    if settings.wa_webhook_secret and not secrets_match(x_webhook_secret, settings.wa_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook secret inválido")
    async with AsyncSessionLocal() as session:
        async with session.begin():
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

    data: dict = payload.get("data", {})
    key: dict = data.get("key", {})

    # send.message é sempre fromMe=true; messages.upsert depende do campo
    from_me: bool = (event == "send.message") or key.get("fromMe", False)

    msg_type_raw: str = data.get("messageType", "conversation")
    body, media = _extract_content(msg_type_raw, data.get("message", {}))

    # Opt-out por palavra-chave (só depende do texto). Se o cliente pediu para
    # parar de receber, NÃO encaminhamos ao n8n — a Raquel não deve puxar
    # conversa com quem acabou de mandar "SAIR" (isso gera denúncia). O registro
    # do consent acontece mais abaixo, já com RLS setado.
    client_opt_out = (not from_me) and opt_out_svc.is_opt_out_keyword(body)

    # Encaminha ao n8n, exceto: send.message (evita loop bot→n8n→bot) e opt-out.
    if event != "send.message" and not client_opt_out:
        background_tasks.add_task(_forward_to_n8n, payload)

    _MSG_EVENTS = ("messages.upsert", "send.message")
    if event not in _MSG_EVENTS:
        return {"ok": True, "skipped": True, "reason": f"event={event}"}

    # Filtra apenas mensagens de contatos individuais
    phone = _extract_phone(key.get("remoteJid", ""))
    if phone is None:
        return {"ok": True, "skipped": True, "reason": "not_individual"}

    # Resolve a org pela instância do payload (multi-tenant). Com mapeamento
    # ausente, cai no comportamento legado single-tenant via settings.
    instance = payload.get("instance", "")
    org_id = await org_id_by_wa_instance(db, instance)
    if org_id is None:
        if settings.evolution_instance_name and instance != settings.evolution_instance_name:
            _logger.warning(
                "wa_webhook instance sem mapeamento e ≠ configurada: got=%r expected=%r",
                instance, settings.evolution_instance_name,
            )
            return {"ok": True, "skipped": True, "reason": "instance_mismatch"}
        org_id = settings.bot_organization_id
    if not org_id:
        _logger.warning("wa_webhook sem org resolvida (instance=%r)", instance)
        return {"ok": True, "skipped": True, "reason": "no_org"}
    await set_current_org(db, org_id)

    sender_type = MessageSenderType.bot if from_me else MessageSenderType.client
    _logger.info("wa_webhook event=%s phone=%s sender=%s", event, mask_phone(phone), sender_type.value)

    wa_message_id: Optional[str] = key.get("id")
    crm_msg_type = _MSG_TYPE_MAP.get(msg_type_raw, MessageType.text)

    opt_out_registered = False
    try:
        await conv_svc.record_message(
            db,
            org_id=org_id,
            phone=phone,
            sender_type=sender_type,
            body=body,
            message_type=crm_msg_type,
            wa_message_id=wa_message_id,
            media=media,
        )
        # Grava o opt-out na MESMA transação da mensagem (atômico). Barra
        # lembrete + reativação, que filtram por esse consent.
        if client_opt_out:
            registered_id = await opt_out_svc.register_opt_out(
                db, org_id=org_id, phone=phone
            )
            opt_out_registered = registered_id is not None
        await db.commit()
    except Exception as exc:
        _logger.error("wa_webhook record_message falhou phone=%s: %s", mask_phone(phone), exc)
        await db.rollback()
        opt_out_registered = False

    # Confirmação fora da transação (I/O de rede; send_text nunca lança e
    # respeita a trava de staging). Só confirma se de fato registrou o consent.
    if opt_out_registered:
        _logger.info("wa_webhook opt-out registrado phone=%s", mask_phone(phone))
        await send_text(phone=phone, message=opt_out_svc.CONFIRMATION)

    return {"ok": True}
