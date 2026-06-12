# file: app/services/reminders.py
"""Lembrete de agendamento via WhatsApp (anti no-show).

Roda por cron (n8n, a cada hora). Alvo: agendamentos 'agendado' que entram na
janela de `reminder_lead_hours` antes do início. Idempotente por agendamento
via `message_log.idempotency_key` — rodadas sobrepostas não duplicam envio.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import local_tz
from app.services.whatsapp import send_text
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    Client,
    ClientConsent,
    ConsentStatus,
    ContactChannel,
    DeliveryStatus,
    MessageDirection,
    MessageLog,
    Service,
)

_logger = logging.getLogger(__name__)

_TEMPLATE = "reminder_24h_v1"

_WEEKDAY_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def idempotency_key(appointment_id: int) -> str:
    return f"{_TEMPLATE}:{appointment_id}"


def build_message(
    client_name: str,
    start_local: datetime,
    service_name: str | None,
    barber_name: str | None,
) -> str:
    first_name = client_name.split()[0] if client_name else "cliente"
    weekday = _WEEKDAY_PT[start_local.weekday()]
    when = f"amanhã ({weekday}) às {start_local.strftime('%H:%M')}"
    svc = f" para *{service_name}*" if service_name else ""
    barber = f" com o {barber_name}" if barber_name else ""

    return (
        f"Oi {first_name}! 👋\n\n"
        f"Passando para lembrar do seu horário {when}{svc}{barber}. ✂️\n\n"
        f"Posso confirmar sua presença? Responda *SIM* para confirmar — "
        f"ou me avise aqui se precisar remarcar ou cancelar."
    )


async def run(org_id: int, session: AsyncSession) -> dict[str, int]:
    """Envia lembretes para agendamentos que entram na janela de lembrete.

    Janela: [agora + lead - window, agora + lead]. Com cron horário e janela de
    2h há sobreposição proposital — o dedup por idempotency_key cobre reenvio
    e rodadas perdidas.
    """
    now_utc = datetime.now(timezone.utc)
    window_end = now_utc + timedelta(hours=settings.reminder_lead_hours)
    window_start = window_end - timedelta(hours=settings.reminder_window_hours)

    rows = (
        await session.execute(
            select(Appointment, Client)
            .join(Client, Client.id == Appointment.client_id)
            .where(Appointment.organization_id == org_id)
            .where(Appointment.status == AppointmentStatus.agendado)
            .where(Appointment.start_at >= window_start)
            .where(Appointment.start_at <= window_end)
            .where(Client.deleted_at.is_(None))
            .where(Client.is_blocked.is_(False))
            .order_by(Appointment.start_at)
        )
    ).all()

    sent = skipped = 0

    for appt, client in rows:
        key = idempotency_key(appt.id)

        already = (
            await session.execute(
                select(MessageLog.id).where(MessageLog.idempotency_key == key).limit(1)
            )
        ).first()
        if already:
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

        item_row = (
            await session.execute(
                select(Service.name, Barber.name)
                .select_from(AppointmentItem)
                .join(Service, Service.id == AppointmentItem.service_id)
                .join(Barber, Barber.id == AppointmentItem.barber_id)
                .where(AppointmentItem.appointment_id == appt.id)
                .limit(1)
            )
        ).first()
        service_name = item_row[0] if item_row else None
        barber_name = item_row[1] if item_row else None

        start_at = (
            appt.start_at
            if appt.start_at.tzinfo
            else appt.start_at.replace(tzinfo=timezone.utc)
        )
        message = build_message(
            client_name=client.name,
            start_local=start_at.astimezone(local_tz()),
            service_name=service_name,
            barber_name=barber_name,
        )

        success = await send_text(phone=client.phone_e164, message=message)

        # Falha não grava a idempotency_key: a próxima rodada dentro da janela
        # tenta de novo (ex.: Evolution API fora do ar por alguns minutos).
        session.add(
            MessageLog(
                organization_id=org_id,
                client_id=client.id,
                appointment_id=appt.id,
                direction=MessageDirection.outbound,
                idempotency_key=key if success else None,
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

    return {"sent": sent, "skipped": skipped, "total_targets": len(rows)}
