"""Helpers de agendamento compartilhados entre painel (agenda) e bot.

Centraliza a regra de conflito de horário para um barbeiro: outro agendamento
ativo OU uma folga (TimeOff) que se sobreponha à janela [start_utc, end_utc).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Appointment, AppointmentItem, TimeOff
from models.enums import AppointmentStatus


async def barber_has_conflict(
    db: AsyncSession,
    barber_id: int,
    start_utc: datetime,
    end_utc: datetime,
    *,
    exclude_appointment_id: int | None = None,
) -> bool:
    """True se o barbeiro tem agendamento ativo ou folga sobrepondo a janela."""
    appt_q = (
        select(Appointment.id)
        .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
        .where(AppointmentItem.barber_id == barber_id)
        .where(Appointment.status != AppointmentStatus.cancelado)
        .where(Appointment.start_at < end_utc)
        .where(Appointment.end_at > start_utc)
        .limit(1)
    )
    if exclude_appointment_id is not None:
        appt_q = appt_q.where(Appointment.id != exclude_appointment_id)

    if (await db.execute(appt_q)).first():
        return True

    time_off_q = (
        select(TimeOff.id)
        .where(TimeOff.barber_id == barber_id)
        .where(TimeOff.start_at < end_utc)
        .where(TimeOff.end_at > start_utc)
        .limit(1)
    )
    return (await db.execute(time_off_q)).first() is not None
