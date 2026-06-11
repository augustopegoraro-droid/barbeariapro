"""Campanha de reativação de clientes inativos via WhatsApp."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.loyalty import resolve_benefit
from models import Barber, Client, DeliveryStatus, MessageDirection, MessageLog, Service
from models.enums import LoyaltyStatus
from models.loyalty import ClientLoyalty

_logger = logging.getLogger(__name__)

_TEMPLATE = "reactivation_v1"


async def run(org_id: int, session: AsyncSession) -> dict[str, int]:
    """Envia mensagens de reativação para clientes em risco ou inativos.

    Verifica cooldown via message_log antes de enviar.
    Retorna contagem de enviados, ignorados e total de alvos.
    """
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.reactivation_cooldown_days
    )

    targets = (
        await session.execute(
            select(ClientLoyalty)
            .where(ClientLoyalty.organization_id == org_id)
            .where(
                ClientLoyalty.status.in_([LoyaltyStatus.em_risco, LoyaltyStatus.inativo])
            )
        )
    ).scalars().all()

    sent = skipped = 0

    for loyalty in targets:
        # Cooldown: pula se já recebeu mensagem de reativação recentemente
        already_sent = (
            await session.execute(
                select(MessageLog.id)
                .where(MessageLog.client_id == loyalty.client_id)
                .where(MessageLog.template == _TEMPLATE)
                .where(MessageLog.delivery_status == DeliveryStatus.sent)
                .where(MessageLog.created_at >= cooldown_cutoff)
                .limit(1)
            )
        ).first()

        if already_sent:
            skipped += 1
            continue

        client = (
            await session.execute(select(Client).where(Client.id == loyalty.client_id))
        ).scalar_one_or_none()
        if not client:
            skipped += 1
            continue

        barber_name: str | None = None
        if loyalty.preferred_barber_id:
            b = (
                await session.execute(
                    select(Barber).where(Barber.id == loyalty.preferred_barber_id)
                )
            ).scalar_one_or_none()
            if b:
                barber_name = b.name

        service_name: str | None = None
        if loyalty.preferred_service_id:
            s = (
                await session.execute(
                    select(Service).where(Service.id == loyalty.preferred_service_id)
                )
            ).scalar_one_or_none()
            if s:
                service_name = s.name

        days_away: int | None = None
        if loyalty.last_visit_at:
            lv = (
                loyalty.last_visit_at
                if loyalty.last_visit_at.tzinfo
                else loyalty.last_visit_at.replace(tzinfo=timezone.utc)
            )
            days_away = (datetime.now(timezone.utc) - lv).days

        message = _build_message(
            name=client.name,
            days_away=days_away,
            barber_name=barber_name,
            service_name=service_name,
            benefit=resolve_benefit(loyalty.nivel, loyalty.categoria),
        )

        success = await _send_whatsapp(phone=client.phone_e164, message=message)

        session.add(
            MessageLog(
                organization_id=org_id,
                client_id=client.id,
                direction=MessageDirection.outbound,
                template=_TEMPLATE,
                delivery_status=DeliveryStatus.sent if success else DeliveryStatus.failed,
                attempt_count=1,
            )
        )
        await session.flush()

        if success:
            sent += 1
        else:
            skipped += 1

    return {"sent": sent, "skipped": skipped, "total_targets": len(targets)}


def _build_message(
    name: str,
    days_away: int | None,
    barber_name: str | None,
    service_name: str | None,
    benefit: str,
) -> str:
    first_name = name.split()[0] if name else "cliente"
    days_part = (
        f"Faz {days_away} dias que não te vemos por aqui"
        if days_away
        else "Há um tempo que você não aparece por aqui"
    )
    barber_part = f"O {barber_name} tá com agenda aberta" if barber_name else "Nossa equipe está pronta"
    service_part = f" — que tal um {service_name}?" if service_name else "?"
    benefit_part = (
        f"\n\nComo cliente especial, você tem direito a: *{benefit}*."
        if benefit != "Sem benefício"
        else ""
    )

    return (
        f"Oi {first_name}! 👋\n\n"
        f"{days_part}. {barber_part}{service_part}{benefit_part}\n\n"
        f"Responda aqui para agendar. 🗓️"
    )


async def _send_whatsapp(phone: str, message: str) -> bool:
    if not settings.evolution_api_url or not settings.evolution_instance_name:
        _logger.warning("Evolution API não configurada — mensagem não enviada para %s", phone)
        return False

    url = f"{settings.evolution_api_url}/message/sendText/{settings.evolution_instance_name}"
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
