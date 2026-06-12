# file: app/services/whatsapp.py
"""Envio de mensagens WhatsApp via Evolution API (helper compartilhado)."""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

_logger = logging.getLogger(__name__)


async def send_text(phone: str, message: str) -> bool:
    """Envia texto para um telefone E.164. Retorna False em qualquer falha."""
    if not settings.evolution_api_url or not settings.evolution_instance_name:
        _logger.warning(
            "Evolution API não configurada — mensagem não enviada para %s", phone
        )
        return False

    url = (
        f"{settings.evolution_api_url}/message/sendText/"
        f"{settings.evolution_instance_name}"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={"number": phone, "text": message},
                headers={"apikey": settings.evolution_api_key},
            )
            resp.raise_for_status()
            return True
    except Exception as exc:
        _logger.error("Falha ao enviar WhatsApp para %s: %s", phone, exc)
        return False
