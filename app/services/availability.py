"""Horários livres (slots) por serviço × profissional × dia (D-79).

Não existia: `scheduling.py` só detecta conflito na criação. Este módulo
calcula a grade de horários disponíveis para o site público — e fica em
`app/services/` para reúso futuro pelo painel e pelo bot.

Regra: grade = `business_hours` da unidade (fuso `unit.timezone`), passo de
30 min; um slot é válido se a janela [início, início + duração do serviço)
cabe inteira numa faixa de funcionamento, não colide com agendamento ativo
nem folga (`TimeOff`) do profissional (mesma semântica de
`barber_has_conflict`, computada em lote para o dia — 1 query de
agendamentos + 1 de folgas, não N chamadas), e começa a pelo menos
`MIN_LEAD_MINUTES` de agora.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Appointment, AppointmentItem, BusinessHours, TimeOff, Unit
from models.enums import AppointmentStatus

SLOT_STEP_MINUTES = 30
MIN_LEAD_MINUTES = 30


async def free_slots(
    db: AsyncSession,
    *,
    unit: Unit,
    barber_id: int,
    duration_minutes: int,
    day: date,
) -> list[datetime]:
    """Inícios de slot livres (datetimes UTC, ordenados) para o dia local."""
    tz = ZoneInfo(unit.timezone)

    # BusinessHours.weekday: 0=domingo ... 6=sábado; date.weekday(): 0=segunda.
    weekday = (day.weekday() + 1) % 7
    hours = (
        (
            await db.execute(
                select(BusinessHours)
                .where(BusinessHours.unit_id == unit.id)
                .where(BusinessHours.weekday == weekday)
                .order_by(BusinessHours.open_time)
            )
        )
        .scalars()
        .all()
    )
    if not hours:
        return []

    day_start = datetime.combine(day, hours[0].open_time, tzinfo=tz).astimezone(timezone.utc)
    day_end = datetime.combine(day, hours[-1].close_time, tzinfo=tz).astimezone(timezone.utc)

    # Ocupações do profissional no dia, em lote (mesma semântica de
    # barber_has_conflict: agendamento não cancelado OU folga sobrepondo).
    busy: list[tuple[datetime, datetime]] = []
    appts = await db.execute(
        select(Appointment.start_at, Appointment.end_at)
        .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
        .where(AppointmentItem.barber_id == barber_id)
        .where(Appointment.status != AppointmentStatus.cancelado)
        .where(Appointment.start_at < day_end)
        .where(Appointment.end_at > day_start)
    )
    busy.extend((row.start_at, row.end_at) for row in appts)
    offs = await db.execute(
        select(TimeOff.start_at, TimeOff.end_at)
        .where(TimeOff.barber_id == barber_id)
        .where(TimeOff.start_at < day_end)
        .where(TimeOff.end_at > day_start)
    )
    busy.extend((row.start_at, row.end_at) for row in offs)

    min_start = datetime.now(timezone.utc) + timedelta(minutes=MIN_LEAD_MINUTES)
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=SLOT_STEP_MINUTES)

    slots: list[datetime] = []
    for window in hours:
        cursor = datetime.combine(day, window.open_time, tzinfo=tz).astimezone(timezone.utc)
        close = datetime.combine(day, window.close_time, tzinfo=tz).astimezone(timezone.utc)
        while cursor + duration <= close:
            if cursor >= min_start and not any(
                b_start < cursor + duration and b_end > cursor for b_start, b_end in busy
            ):
                slots.append(cursor)
            cursor += step
    return slots
