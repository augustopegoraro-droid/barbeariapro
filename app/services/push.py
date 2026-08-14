# file: app/services/push.py
"""Notificações push (Web Push/VAPID) — profissionais e clientes finais.

Molde de idempotência de `app/services/reminders.py`: cada disparo reserva
ATOMICAMENTE uma linha de `push_notification_log` (INSERT ... ON CONFLICT DO
NOTHING na unique de `idempotency_key`) antes de enviar — rodadas concorrentes
(cron sobreposto, retry) perdem o claim e não reenviam. Canal independente do
WhatsApp: uma falha aqui nunca afeta `reminders.py`/`MessageLog`.

Sem subscrição ativa para o assinante conta como "sem alvo" (`no_target`), não
como falha — a key já foi consumida (sem retry pontual), mas isso não bloqueia
nada: é só um disparo perdido para quem ainda não ativou notificação.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import local_tz
from app.db.session import AsyncSessionLocal, set_current_org
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    Client,
    DeliveryStatus,
    PushNotificationLog,
    PushSubscriberType,
    PushSubscription,
    Service,
    UserUnit,
)

_logger = logging.getLogger(__name__)

_WEEKDAY_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _vapid_configured() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def _fmt_when(start_local: datetime) -> str:
    weekday = _WEEKDAY_PT[start_local.weekday()]
    return f"{weekday}, {start_local.strftime('%d/%m')} às {start_local.strftime('%H:%M')}"


async def send_push(
    db: AsyncSession,
    subscription: PushSubscription,
    *,
    title: str,
    body: str,
    url: str | None = None,
    tag: str | None = None,
) -> bool:
    """Envia para UM dispositivo. Revoga a subscrição em 404/410 (morta)."""
    if not _vapid_configured():
        _logger.warning("push: VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY ausentes — envio ignorado")
        return False

    from pywebpush import WebPushException, webpush  # import tardio: dep opcional fora de prod

    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth_key},
            },
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
        await db.execute(
            update(PushSubscription)
            .where(PushSubscription.id == subscription.id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        return True
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            await db.execute(
                update(PushSubscription)
                .where(PushSubscription.id == subscription.id)
                .values(revoked_at=datetime.now(timezone.utc))
            )
        else:
            _logger.warning(
                "push: falha ao enviar (subscription_id=%s, status=%s): %s",
                subscription.id, status_code, exc,
            )
        return False


async def _active_subscriptions(
    db: AsyncSession, org_id: int, *, user_id: int | None = None, client_id: int | None = None
) -> list[PushSubscription]:
    stmt = select(PushSubscription).where(
        PushSubscription.organization_id == org_id,
        PushSubscription.revoked_at.is_(None),
    )
    stmt = stmt.where(PushSubscription.user_id == user_id) if user_id is not None else stmt
    stmt = stmt.where(PushSubscription.client_id == client_id) if client_id is not None else stmt
    return list((await db.execute(stmt)).scalars().all())


async def dispatch(
    db: AsyncSession,
    *,
    org_id: int,
    kind: str,
    idempotency_key: str,
    subscriber_type: PushSubscriberType,
    user_id: int | None,
    client_id: int | None,
    appointment_id: int | None,
    title: str,
    body: str,
    url: str | None = None,
) -> str:
    """Reserva a `idempotency_key`, envia a todos os dispositivos ativos do
    assinante e grava o resultado. Retorna "sent" | "skipped" | "no_target".
    """
    claimed_id = (
        await db.execute(
            pg_insert(PushNotificationLog)
            .values(
                organization_id=org_id,
                subscriber_type=subscriber_type,
                user_id=user_id,
                client_id=client_id,
                appointment_id=appointment_id,
                kind=kind,
                idempotency_key=idempotency_key,
                delivery_status=DeliveryStatus.pending,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(PushNotificationLog.id)
        )
    ).scalar_one_or_none()
    if claimed_id is None:
        return "skipped"

    subs = await _active_subscriptions(db, org_id, user_id=user_id, client_id=client_id)
    if not subs:
        await db.execute(
            update(PushNotificationLog)
            .where(PushNotificationLog.id == claimed_id)
            .values(delivery_status=DeliveryStatus.failed)
        )
        return "no_target"

    any_sent = False
    for sub in subs:
        ok = await send_push(db, sub, title=title, body=body, url=url, tag=kind)
        any_sent = any_sent or ok

    await db.execute(
        update(PushNotificationLog)
        .where(PushNotificationLog.id == claimed_id)
        .values(delivery_status=DeliveryStatus.sent if any_sent else DeliveryStatus.failed)
    )
    return "sent" if any_sent else "no_target"


async def _appointment_details(
    db: AsyncSession, appointment_id: int
) -> tuple[Appointment, Client, str | None, str | None, int | None] | None:
    row = (
        await db.execute(
            select(Appointment, Client, Service.name, Barber.name, Barber.id)
            .join(Client, Client.id == Appointment.client_id)
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .join(Service, Service.id == AppointmentItem.service_id)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .where(Appointment.id == appointment_id)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    appt, client, service_name, barber_name, barber_id = row
    return appt, client, service_name, barber_name, barber_id


async def notify_booking_confirmation(appointment_id: int, org_id: int) -> None:
    """Confirmação imediata pro CLIENTE ao agendar pelo site público.

    Chamado como `BackgroundTasks` a partir de `app/api/public.py::
    book_appointment` (mesmo padrão de `calendar_sync.push_appointment`: abre
    a própria sessão, nunca reusa a do request — a resposta já foi enviada).
    """
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await set_current_org(session, org_id)
                details = await _appointment_details(session, appointment_id)
                if details is None:
                    return
                appt, client, service_name, barber_name, _barber_id = details
                start_local = appt.start_at.astimezone(local_tz())
                svc = f" para *{service_name}*" if service_name else ""
                barber = f" com {barber_name}" if barber_name else ""
                await dispatch(
                    session,
                    org_id=org_id,
                    kind="booking_confirmation",
                    idempotency_key=f"booking_confirmation_v1:{appointment_id}",
                    subscriber_type=PushSubscriberType.client,
                    user_id=None,
                    client_id=client.id,
                    appointment_id=appointment_id,
                    title="Agendamento confirmado ✂️",
                    body=f"Seu horário{svc}{barber} ficou marcado para {_fmt_when(start_local)}.",
                )
    except Exception:
        _logger.exception(
            "push: erro não tratado na confirmação de agendamento [appt=%s org=%s]",
            appointment_id, org_id,
        )


async def run_near_reminders(org_id: int, session: AsyncSession) -> dict[str, int]:
    """Lembretes "de última hora" (cliente e profissional), janela curta.

    Janela: [agora + lead - window, agora + lead], lead/window em MINUTOS
    (`push_client_near_lead_minutes`/`push_professional_lead_minutes`,
    `push_near_window_minutes`) — cadência do cron é bem mais fina que o
    lembrete de 24h (n8n roda este a cada ~10min, não de hora em hora).
    """
    now_utc = datetime.now(timezone.utc)
    window = timedelta(minutes=settings.push_near_window_minutes)
    client_end = now_utc + timedelta(minutes=settings.push_client_near_lead_minutes)
    barber_end = now_utc + timedelta(minutes=settings.push_professional_lead_minutes)
    window_start = min(client_end, barber_end) - window
    window_end = max(client_end, barber_end)

    rows = (
        await session.execute(
            select(Appointment, Client, Service.name, Barber.name, Barber.id)
            .join(Client, Client.id == Appointment.client_id)
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .join(Service, Service.id == AppointmentItem.service_id)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .where(Appointment.organization_id == org_id)
            .where(Appointment.status == AppointmentStatus.agendado)
            .where(Appointment.start_at >= window_start)
            .where(Appointment.start_at <= window_end)
            .where(Client.deleted_at.is_(None))
            .order_by(Appointment.start_at)
        )
    ).all()

    sent = skipped = 0
    for appt, client, service_name, barber_name, barber_id in rows:
        start_local = appt.start_at.astimezone(local_tz())
        when = _fmt_when(start_local)

        # Cliente: dentro da janela dele.
        if client_end - window <= appt.start_at <= client_end:
            svc = f" para *{service_name}*" if service_name else ""
            barber = f" com {barber_name}" if barber_name else ""
            result = await dispatch(
                session,
                org_id=org_id,
                kind="reminder_30m",
                idempotency_key=f"reminder_near_client_v1:{appt.id}:{appt.start_at:%Y%m%dT%H%M}",
                subscriber_type=PushSubscriberType.client,
                user_id=None,
                client_id=client.id,
                appointment_id=appt.id,
                title="Seu horário está chegando ⏰",
                body=f"Seu horário{svc}{barber} é {when}.",
            )
            sent += result == "sent"
            skipped += result != "sent"

        # Profissional: usuários da equipe ligados a esse barbeiro.
        if barber_end - window <= appt.start_at <= barber_end:
            user_ids = (
                await session.execute(
                    select(UserUnit.user_id).where(UserUnit.barber_id == barber_id)
                )
            ).scalars().all()
            for user_id in user_ids:
                result = await dispatch(
                    session,
                    org_id=org_id,
                    kind="reminder_30m",
                    idempotency_key=(
                        f"reminder_near_barber_v1:{appt.id}:{user_id}:"
                        f"{appt.start_at:%Y%m%dT%H%M}"
                    ),
                    subscriber_type=PushSubscriberType.user,
                    user_id=user_id,
                    client_id=None,
                    appointment_id=appt.id,
                    title="Próximo atendimento ⏰",
                    body=f"{client.name} — {service_name or 'atendimento'} às "
                    f"{start_local.strftime('%H:%M')}.",
                )
                sent += result == "sent"
                skipped += result != "sent"

    return {"sent": sent, "skipped": skipped, "total_targets": len(rows)}
