"""Endpoint de gestão de equipe: barbeiros, horários e folgas."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_manager_access, resolve_role
from app.deps import get_current_user, get_tenant_db
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BarberUnit,
    BusinessHours,
    TimeOff,
    Unit,
    User,
    UserUnit,
)

router = APIRouter(prefix="/equipe", tags=["equipe"])

WEEKDAY_PT = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]


class BusinessHoursOut(BaseModel):
    weekday: int
    weekday_label: str
    open_time: str
    close_time: str


class TimeOffOut(BaseModel):
    id: int
    start_at: str
    end_at: str
    reason: Optional[str]


class BarberOut(BaseModel):
    id: int
    name: str
    specialty: Optional[str]
    commission_pct: float
    concluido_count: int
    agendado_count: int
    business_hours: list[BusinessHoursOut]
    upcoming_time_off: list[TimeOffOut]


class EquipeOut(BaseModel):
    barbers: list[BarberOut]


@router.get("", response_model=EquipeOut)
async def get_equipe(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> EquipeOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    require_manager_access(resolve_role(list(unit_links)))

    # Barbeiros ativos da organização
    barbers = (
        await db.execute(
            select(Barber)
            .where(Barber.deleted_at.is_(None))
            .order_by(Barber.name)
        )
    ).scalars().all()

    if not barbers:
        return EquipeOut(barbers=[])

    barber_ids = [b.id for b in barbers]

    # Contagem de agendamentos por barbeiro (todos os tempos)
    count_rows = (
        await db.execute(
            select(
                AppointmentItem.barber_id,
                Appointment.status,
                func.count(Appointment.id.distinct()).label("cnt"),
            )
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(
                AppointmentItem.barber_id.in_(barber_ids),
                Appointment.status.in_([AppointmentStatus.concluido, AppointmentStatus.agendado]),
            )
            .group_by(AppointmentItem.barber_id, Appointment.status)
        )
    ).all()

    stats: dict[int, dict[str, int]] = {b.id: {"concluido": 0, "agendado": 0} for b in barbers}
    for row in count_rows:
        stats[row.barber_id][row.status.value] = row.cnt

    # Unidades de cada barbeiro
    barber_unit_rows = (
        await db.execute(
            select(BarberUnit.barber_id, BarberUnit.unit_id)
            .where(BarberUnit.barber_id.in_(barber_ids))
        )
    ).all()

    unit_ids = list({r.unit_id for r in barber_unit_rows})
    barber_to_units: dict[int, list[int]] = {b.id: [] for b in barbers}
    for r in barber_unit_rows:
        barber_to_units[r.barber_id].append(r.unit_id)

    # Horários de funcionamento das unidades
    bh_rows = (
        await db.execute(
            select(BusinessHours)
            .where(BusinessHours.unit_id.in_(unit_ids))
            .order_by(BusinessHours.unit_id, BusinessHours.weekday)
        )
    ).scalars().all()

    bh_by_unit: dict[int, list[BusinessHoursOut]] = {}
    for bh in bh_rows:
        bh_by_unit.setdefault(bh.unit_id, []).append(
            BusinessHoursOut(
                weekday=bh.weekday,
                weekday_label=WEEKDAY_PT[bh.weekday],
                open_time=bh.open_time.strftime("%H:%M"),
                close_time=bh.close_time.strftime("%H:%M"),
            )
        )

    # Folgas futuras dos barbeiros
    now_utc = datetime.now(timezone.utc)
    time_off_rows = (
        await db.execute(
            select(TimeOff)
            .where(
                TimeOff.barber_id.in_(barber_ids),
                TimeOff.end_at >= now_utc,
            )
            .order_by(TimeOff.barber_id, TimeOff.start_at)
        )
    ).scalars().all()

    time_off_by_barber: dict[int, list[TimeOffOut]] = {b.id: [] for b in barbers}
    for t in time_off_rows:
        time_off_by_barber[t.barber_id].append(
            TimeOffOut(
                id=t.id,
                start_at=t.start_at.isoformat(),
                end_at=t.end_at.isoformat(),
                reason=t.reason,
            )
        )

    # Montar resposta: horários = união das unidades do barbeiro (dedup por weekday+slot)
    result = []
    for b in barbers:
        seen_bh: set[tuple] = set()
        hours: list[BusinessHoursOut] = []
        for uid in barber_to_units.get(b.id, []):
            for bh in bh_by_unit.get(uid, []):
                key = (bh.weekday, bh.open_time, bh.close_time)
                if key not in seen_bh:
                    seen_bh.add(key)
                    hours.append(bh)
        hours.sort(key=lambda h: h.weekday)

        result.append(
            BarberOut(
                id=b.id,
                name=b.name,
                specialty=b.specialty,
                commission_pct=float(b.commission_pct),
                concluido_count=stats[b.id]["concluido"],
                agendado_count=stats[b.id]["agendado"],
                business_hours=hours,
                upcoming_time_off=time_off_by_barber[b.id],
            )
        )

    return EquipeOut(barbers=result)
