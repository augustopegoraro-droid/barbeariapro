# file: app/services/reminders.py
"""Lembrete de agendamento via WhatsApp (anti no-show).

Roda por cron (n8n, a cada hora). Alvo: agendamentos 'agendado' que entram na
janela de `reminder_lead_hours` antes do início. Idempotente por agendamento: a
`message_log.idempotency_key` é RESERVADA atomicamente (INSERT ... ON CONFLICT DO
NOTHING na UNIQUE) ANTES do envio — rodadas concorrentes (retry do n8n, cron
sobreposto, multi-processo) perdem o claim e não reenviam.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import local_tz
from app.services.whatsapp import send_text
import app.services.conversation as _conv_svc
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
    Organization,
    Service,
)
from models.enums import MessageSenderType, MessageType

_logger = logging.getLogger(__name__)

_TEMPLATE = "reminder_24h_v1"

_WEEKDAY_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def idempotency_key(appointment_id: int, start_at: datetime) -> str:
    # start_at na key: agendamento remarcado gera key nova e recebe novo lembrete
    return f"{_TEMPLATE}:{appointment_id}:{start_at.strftime('%Y%m%dT%H%M')}"


def build_message(
    client_name: str,
    start_local: datetime,
    service_name: str | None,
    barber_name: str | None,
    business_name: str | None = None,
) -> str:
    first_name = client_name.split()[0] if client_name else "cliente"
    weekday = _WEEKDAY_PT[start_local.weekday()]
    when = f"amanhã ({weekday}) às {start_local.strftime('%H:%M')}"
    svc = f" para *{service_name}*" if service_name else ""
    barber = f" com o {barber_name}" if barber_name else ""
    # Identifica o remetente (número novo/reativado): reduz "quem é esse?" e
    # o risco de denúncia — o cliente reconhece o negócio no 1º contato.
    greeting = (
        f"Oi {first_name}! 👋 Aqui é da *{business_name}*."
        if business_name
        else f"Oi {first_name}! 👋"
    )

    return (
        f"{greeting}\n\n"
        f"Passando pra lembrar do seu horário {when}{svc}{barber}. ✂️\n\n"
        f"Consegue confirmar presença? Responde *SIM* que já deixo certinho — "
        f"ou me avisa aqui se precisar remarcar. 🙂"
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

    # Nome comercial p/ identificar o remetente nas mensagens (uma busca por run).
    business_name = (
        await session.execute(
            select(Organization.name).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()

    for appt, client in rows:
        key = idempotency_key(appt.id, appt.start_at)

        # opt-out é filtro read-only (sem corrida) — barra antes de reservar a key.
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

        # Claim ATÔMICO da idempotency_key ANTES do envio — fecha o TOCTOU que
        # duplicava. O antigo SELECT-then-send deixava rodadas concorrentes verem
        # "ainda não enviado" ao mesmo tempo e disparar todas (2x/4x com retry do
        # n8n). `INSERT ... ON CONFLICT DO NOTHING` adquire o lock do índice unique
        # já no INSERT: só o vencedor do claim envia; as concorrentes recebem
        # `None` (DO NOTHING, sem IntegrityError) e pulam sem reenviar.
        claimed_id = (
            await session.execute(
                pg_insert(MessageLog)
                .values(
                    organization_id=org_id,
                    client_id=client.id,
                    appointment_id=appt.id,
                    direction=MessageDirection.outbound,
                    idempotency_key=key,
                    template=_TEMPLATE,
                    delivery_status=DeliveryStatus.pending,
                    attempt_count=1,
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
                .returning(MessageLog.id)
            )
        ).scalar_one_or_none()
        if claimed_id is None:
            # outra rodada dentro da janela já reservou/enviou este lembrete.
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
            business_name=business_name,
        )

        success = await send_text(phone=client.phone_e164, message=message)

        if success:
            await session.execute(
                update(MessageLog)
                .where(MessageLog.id == claimed_id)
                .values(delivery_status=DeliveryStatus.sent)
            )
            await _conv_svc.record_message(
                session,
                org_id=org_id,
                phone=client.phone_e164,
                sender_type=MessageSenderType.system,
                body=message,
                message_type=MessageType.text,
                message_log_id=claimed_id,
            )
            sent += 1
        else:
            # Envio falhou (ex.: Evolution fora do ar): LIBERA a reserva
            # (idempotency_key=NULL) para a próxima rodada dentro da janela
            # retentar — sem a reserva presa bloqueando o retry.
            await session.execute(
                update(MessageLog)
                .where(MessageLog.id == claimed_id)
                .values(delivery_status=DeliveryStatus.failed, idempotency_key=None)
            )
            skipped += 1

    return {"sent": sent, "skipped": skipped, "total_targets": len(rows)}
