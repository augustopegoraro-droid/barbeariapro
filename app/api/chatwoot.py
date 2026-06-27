# file: app/api/chatwoot.py
"""Webhook do Chatwoot → FastAPI (D-49, Fase 4 — esqueleto).

O Chatwoot passa a ser a camada de conversa/atendimento; o FUNIL continua aqui no
backend. Este router recebe eventos do Chatwoot e:
- grava a mensagem pela porta única (`services/conversation.record_message`),
  idempotente pelo id da mensagem do Chatwoot;
- no inbound de cliente, avança o lead reusando `lead_funnel.advance_lead_on_inbound`
  (mesmo caminho do /bot — NÃO duplica a transição de estágio, Regra de Ouro do CRM).

⚠️ Status: esqueleto. O Chatwoot ainda não existe (Fases 0–2 pendentes). Hoje o
endpoint só avança lead JÁ existente (igual ao /bot/messages); a criação de
cliente/lead a partir do Chatwoot e o envio reverso ficam como follow-up (TODO).
Seguro por padrão: 503 sem token configurado, 401 com token inválido.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.phone import normalize_phone
from app.core.security import secrets_match
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import conversation as conv_svc
from app.services.lead_funnel import advance_lead_on_inbound
from models import Client
from models.enums import MessageSenderType, MessageType

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatwoot", tags=["chatwoot"])

# Evento do Chatwoot que carrega texto (cliente/atendente/bot).
_MESSAGE_EVENT = "message_created"

# sender.type do Chatwoot → quem enviou, no nosso modelo de conversa.
_SENDER_MAP = {
    "contact": MessageSenderType.client,   # cliente final
    "user": MessageSenderType.human,       # atendente humano
    "agent_bot": MessageSenderType.bot,    # Raquel (Agent Bot)
}


@dataclass
class ParsedChatwootMessage:
    """Resultado PURO do parse de um webhook `message_created` do Chatwoot."""
    chatwoot_message_id: Optional[str]
    sender_type: MessageSenderType
    is_incoming: bool
    raw_phone: Optional[str]
    body: Optional[str]
    conversation_id: Optional[int]
    conversation_status: Optional[str]


def _extract_phone_raw(payload: dict) -> Optional[str]:
    """Telefone do contato: `sender.phone_number` ou `conversation.meta.sender`."""
    sender = payload.get("sender") or {}
    phone = sender.get("phone_number")
    if phone:
        return phone
    meta = (payload.get("conversation") or {}).get("meta") or {}
    msender = meta.get("sender") or {}
    return msender.get("phone_number")


def _resolve_sender(payload: dict) -> tuple[MessageSenderType, bool]:
    """Devolve (sender_type, is_incoming).

    `message_type` vem como "incoming"/"outgoing" (string) ou 0/1 (int), conforme a
    versão do Chatwoot. Preferimos `sender.type`; se ausente, caímos na direção.
    """
    raw_mt = payload.get("message_type")
    is_incoming = raw_mt in ("incoming", 0, "0")
    sender = payload.get("sender") or {}
    stype = _SENDER_MAP.get((sender.get("type") or "").lower())
    if stype is not None:
        return stype, is_incoming
    return (MessageSenderType.client if is_incoming else MessageSenderType.human), is_incoming


def parse_chatwoot_message(payload: dict) -> Optional[ParsedChatwootMessage]:
    """Parser PURO (testável sem DB). Retorna None se não for `message_created`."""
    if payload.get("event") != _MESSAGE_EVENT:
        return None
    conv = payload.get("conversation") or {}
    sender_type, is_incoming = _resolve_sender(payload)
    msg_id = payload.get("id")
    return ParsedChatwootMessage(
        chatwoot_message_id=str(msg_id) if msg_id is not None else None,
        sender_type=sender_type,
        is_incoming=is_incoming,
        raw_phone=_extract_phone_raw(payload),
        body=payload.get("content"),
        conversation_id=conv.get("id"),
        conversation_status=conv.get("status"),
    )


async def _get_chatwoot_db(
    x_chatwoot_token: Annotated[Optional[str], Header(alias="X-Chatwoot-Token")] = None,
) -> AsyncIterator[AsyncSession]:
    """Sessão DB para o webhook do Chatwoot. Token obrigatório (seguro por padrão).

    Comparação em tempo constante (`secrets_match`). Org fixa de settings (RLS),
    como o caminho do bot — Chatwoot é single-tenant por ora (produção = org 1).
    """
    if not settings.chatwoot_webhook_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="CHATWOOT_WEBHOOK_TOKEN não configurado")
    if not secrets_match(x_chatwoot_token, settings.chatwoot_webhook_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token do webhook Chatwoot inválido")
    if not settings.bot_organization_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="BOT_ORGANIZATION_ID não configurado")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, settings.bot_organization_id)
            yield session


@router.post("/webhook", status_code=200)
async def chatwoot_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(_get_chatwoot_db)],
) -> dict:
    """Recebe webhook do Chatwoot; mantém conversa + funil no backend.

    Trata `message_created`: grava a mensagem (idempotente pelo id do Chatwoot) e,
    no inbound de cliente, avança o lead ativo (helper compartilhado com /bot).
    Outros eventos são ignorados com 200 (ack) para não disparar retry do Chatwoot.
    """
    payload: dict = await request.json()
    parsed = parse_chatwoot_message(payload)
    if parsed is None:
        return {"ok": True, "skipped": True, "reason": f"event={payload.get('event')}"}

    if not parsed.raw_phone:
        return {"ok": True, "skipped": True, "reason": "no_phone"}
    try:
        phone = normalize_phone(parsed.raw_phone)
    except HTTPException:
        return {"ok": True, "skipped": True, "reason": "invalid_phone"}

    org_id = settings.bot_organization_id
    now = datetime.now(timezone.utc)

    _logger.info(
        "chatwoot_webhook sender=%s incoming=%s phone=%s conv=%s msg=%s",
        parsed.sender_type.value, parsed.is_incoming, phone,
        parsed.conversation_id, parsed.chatwoot_message_id,
    )

    try:
        client = (
            await db.execute(
                select(Client)
                .where(Client.organization_id == org_id)
                .where(Client.phone_e164 == phone)
            )
        ).scalar_one_or_none()

        msg = await conv_svc.record_message(
            db,
            org_id=org_id,
            phone=phone,
            sender_type=parsed.sender_type,
            body=parsed.body,
            message_type=MessageType.text,
            wa_message_id=parsed.chatwoot_message_id,  # idempotência pelo id do Chatwoot
            client_id=client.id if client else None,
        )

        if msg is None:
            await db.commit()
            return {"ok": True, "duplicate": True}

        # Avanço de estágio só no inbound de cliente — caminho ÚNICO (não duplica).
        # TODO(Fase 4 completa): upsert de cliente/lead p/ 1º contato vindo do Chatwoot.
        if (parsed.is_incoming
                and parsed.sender_type == MessageSenderType.client
                and client is not None):
            await advance_lead_on_inbound(db, org_id=org_id, client_id=client.id, now=now)

        await db.commit()
    except Exception as exc:  # ack 200 mesmo em erro, evita retry-storm do Chatwoot
        _logger.error("chatwoot_webhook record falhou phone=%s: %s", phone, exc)
        await db.rollback()
        return {"ok": False, "error": "internal"}

    return {"ok": True, "duplicate": False}
