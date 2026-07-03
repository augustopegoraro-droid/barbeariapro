"""Campanha de reativação de clientes inativos via WhatsApp."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.loyalty import resolve_benefit
from app.services.whatsapp import send_text
import app.services.conversation as _conv_svc
from models import (
    Barber,
    Client,
    ClientConsent,
    ConsentStatus,
    ContactChannel,
    DeliveryStatus,
    MessageDirection,
    MessageLog,
    Organization,
    Service,
)
from models.enums import LoyaltyStatus, MessageSenderType, MessageType
from models.loyalty import ClientLoyalty

_logger = logging.getLogger(__name__)

_TEMPLATE = "reactivation_v1"

# Teto de ENVIOS novos por rodada — evita rajada quando a fila de inativos
# encher (ex.: pós-import de milhares de clientes). Sem isto o loop dispararia
# todos de uma vez, o que o WhatsApp lê como spam. O cooldown já espaça o resto
# ao longo dos dias. Ajustável por chamada.
_DEFAULT_BATCH_LIMIT = 40
# Teto de candidatos lidos por rodada (proteção de memória — não carregar
# milhares de linhas quando só vamos enviar algumas dezenas).
_CANDIDATE_SCAN_CAP = 500


async def run(
    org_id: int,
    session: AsyncSession,
    batch_limit: int = _DEFAULT_BATCH_LIMIT,
) -> dict[str, int]:
    """Envia mensagens de reativação para clientes em risco ou inativos.

    Verifica cooldown via message_log antes de enviar. Envia no máximo
    ``batch_limit`` mensagens NOVAS por rodada (anti-rajada); o cooldown
    espalha o restante pelas rodadas seguintes. Retorna contagem de
    enviados, ignorados e total de alvos lidos.
    """
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.reactivation_cooldown_days
    )

    # Prioriza quem saiu há menos tempo (maior chance de retorno) e limita a
    # leitura — o corte real de ritmo é o `break` no batch_limit abaixo.
    targets = (
        await session.execute(
            select(ClientLoyalty, Client)
            .join(Client, Client.id == ClientLoyalty.client_id)
            .where(ClientLoyalty.organization_id == org_id)
            .where(
                ClientLoyalty.status.in_([LoyaltyStatus.em_risco, LoyaltyStatus.inativo])
            )
            .where(Client.deleted_at.is_(None))
            .where(Client.is_blocked.is_(False))
            .order_by(ClientLoyalty.last_visit_at.desc().nulls_last())
            .limit(_CANDIDATE_SCAN_CAP)
        )
    ).all()

    sent = skipped = 0

    # Nome comercial p/ identificar o remetente (uma busca por run).
    business_name = (
        await session.execute(
            select(Organization.name).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()

    for loyalty, client in targets:
        # Anti-rajada: para no teto de envios da rodada; o resto vai na próxima.
        if sent >= batch_limit:
            break
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

        opted_out = (
            await session.execute(
                select(ClientConsent.id)
                .where(ClientConsent.client_id == client.id)
                .where(ClientConsent.channel == ContactChannel.whatsapp)
                .where(ClientConsent.status == ConsentStatus.opt_out)
                .limit(1)
            )
        ).first()
        if opted_out:
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
            business_name=business_name,
        )

        success = await send_text(phone=client.phone_e164, message=message)

        log = MessageLog(
            organization_id=org_id,
            client_id=client.id,
            direction=MessageDirection.outbound,
            template=_TEMPLATE,
            delivery_status=DeliveryStatus.sent if success else DeliveryStatus.failed,
            attempt_count=1,
        )
        session.add(log)
        await session.flush()

        if success:
            await _conv_svc.record_message(
                session,
                org_id=org_id,
                phone=client.phone_e164,
                sender_type=MessageSenderType.system,
                body=message,
                message_type=MessageType.text,
                message_log_id=log.id,
            )
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
    business_name: str | None = None,
) -> str:
    first_name = name.split()[0] if name else "cliente"
    greeting = (
        f"Oi {first_name}! 👋 Aqui é da *{business_name}*."
        if business_name
        else f"Oi {first_name}! 👋"
    )
    # Sem número exato de dias: "faz 90 dias" soa robótico e denuncia automação.
    # A saudação varia pela faixa de inatividade (personalização honesta, não
    # técnica de evasão — reflete o dado real de quão tempo o cliente sumiu).
    if days_away and days_away >= 120:
        saudade = "Já faz um bom tempo que você não aparece e a saudade bateu! 😊"
    elif days_away and days_away >= 45:
        saudade = "Faz um tempinho que você não passa por aqui e bateu a saudade! 😊"
    else:
        saudade = "Senti sua falta por aqui! 😊"
    if barber_name:
        convite = f"O {barber_name} tá com horários abertos"
    else:
        convite = "A equipe tá com horários abertos"
    convite += (
        f" — bora marcar um {service_name}?" if service_name else " essa semana. Bora marcar?"
    )
    benefit_part = (
        f"\n\nE tem um mimo te esperando: *{benefit}*. 🎁"
        if benefit != "Sem benefício"
        else ""
    )

    return (
        f"{greeting}\n\n"
        f"{saudade} {convite}{benefit_part}\n\n"
        f"Se quiser, é só me responder por aqui. 🗓️"
    )
