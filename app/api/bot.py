# file: app/api/bot.py
"""Endpoints consumidos pelo chatbot n8n (auth via X-Bot-Token)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.deps import get_bot_db
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BarberUnit,
    BusinessHours,
    Client,
    ClientConsent,
    ConsentStatus,
    ContactChannel,
    Service,
    TimeOff,
    Unit,
)

router = APIRouter(prefix="/bot", tags=["bot"])
BotDB = Annotated[AsyncSession, Depends(get_bot_db)]

_SLOT_STEP = 30  # minutos entre slots
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


# ---------------------------------------------------------------------------
# Schemas de saída/entrada
# ---------------------------------------------------------------------------


class ServiceOut(BaseModel):
    id: int
    name: str
    category: str
    price: Decimal
    duration_min: int


class BarberOut(BaseModel):
    id: int
    name: str
    specialty: Optional[str] = None


class ClientUpsertIn(BaseModel):
    phone: str = Field(..., description="Telefone E.164 ex: +5511999998888")
    name: str


class ClientOut(BaseModel):
    id: int
    name: str
    phone_e164: str


class Slot(BaseModel):
    start: str       # "09:00"
    end: str         # "09:30"
    start_iso: str   # ISO com fuso


class AvailabilityOut(BaseModel):
    date: str
    barber_id: int
    barber_name: str
    service_duration_min: int
    slots: List[Slot]


class AppointmentCreateIn(BaseModel):
    client_id: int
    barber_id: int
    service_id: int
    start_at: datetime = Field(
        ..., description="ISO 8601 com fuso ex: 2026-06-05T09:00:00-03:00"
    )


class AppointmentOut(BaseModel):
    id: int
    public_id: str
    barber_name: str
    service_name: str
    start_at: str
    end_at: str
    status: str
    total_amount: Decimal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_phone(raw: str) -> str:
    raw = raw.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not raw.startswith("+"):
        raw = "+" + raw
    if not _E164.match(raw):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Telefone inválido: '{raw}'. Use formato E.164 (+5511999998888)",
        )
    return raw


def _overlaps(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> bool:
    return s2 < e1 and e2 > s1


def _appt_out(appt: Appointment, barber_name: str, svc_name: str) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        public_id=str(appt.public_id),
        barber_name=barber_name,
        service_name=svc_name,
        start_at=appt.start_at.isoformat(),
        end_at=appt.end_at.isoformat(),
        status=appt.status.value,
        total_amount=appt.total_amount,
    )


# ---------------------------------------------------------------------------
# Serviços
# ---------------------------------------------------------------------------


@router.get("/services", response_model=List[ServiceOut])
async def list_services(db: BotDB) -> list:
    rows = (
        await db.execute(select(Service).where(Service.is_active.is_(True)))
    ).scalars().all()
    return [
        ServiceOut(
            id=s.id,
            name=s.name,
            category=s.category.value,
            price=s.price,
            duration_min=s.default_duration_min,
        )
        for s in rows
    ]


# ---------------------------------------------------------------------------
# Barbeiros
# ---------------------------------------------------------------------------


@router.get("/barbers", response_model=List[BarberOut])
async def list_barbers(db: BotDB) -> list:
    rows = (
        await db.execute(
            select(Barber)
            .join(BarberUnit, BarberUnit.barber_id == Barber.id)
            .where(BarberUnit.unit_id == settings.bot_unit_id)
            .where(Barber.deleted_at.is_(None))
        )
    ).scalars().all()
    return [BarberOut(id=b.id, name=b.name, specialty=b.specialty) for b in rows]


# ---------------------------------------------------------------------------
# Clientes (upsert por telefone)
# ---------------------------------------------------------------------------


@router.post("/clients", response_model=ClientOut, status_code=status.HTTP_200_OK)
async def upsert_client(body: ClientUpsertIn, db: BotDB) -> ClientOut:
    phone = _normalize_phone(body.phone)
    org_id = settings.bot_organization_id

    existing = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()

    if existing:
        existing.name = body.name
        client = existing
    else:
        client = Client(
            organization_id=org_id,
            name=body.name,
            phone_e164=phone,
            acquisition_channel=ContactChannel.whatsapp,
        )
        db.add(client)
        await db.flush()
        db.add(
            ClientConsent(
                client_id=client.id,
                channel=ContactChannel.whatsapp,
                status=ConsentStatus.opt_in,
                source="chatbot_first_contact",
            )
        )

    return ClientOut(id=client.id, name=client.name, phone_e164=client.phone_e164)


# ---------------------------------------------------------------------------
# Disponibilidade
# ---------------------------------------------------------------------------


@router.get("/availability", response_model=AvailabilityOut)
async def get_availability(
    barber_id: int,
    service_id: int,
    date: date,
    db: BotDB,
) -> AvailabilityOut:
    org_id = settings.bot_organization_id
    unit_id = settings.bot_unit_id

    svc = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if not svc:
        raise HTTPException(404, "Serviço não encontrado")
    duration = svc.default_duration_min

    barber = (await db.execute(select(Barber).where(Barber.id == barber_id))).scalar_one_or_none()
    if not barber:
        raise HTTPException(404, "Barbeiro não encontrado")

    unit = (await db.execute(select(Unit).where(Unit.id == unit_id))).scalar_one_or_none()
    tz_name = unit.timezone if unit else "America/Sao_Paulo"
    tz = ZoneInfo(tz_name)

    # schema: weekday 0=Dom, 1=Seg, ..., 6=Sáb; Python weekday(): 0=Seg,...,6=Dom
    pg_weekday = (date.weekday() + 1) % 7

    bh_rows = (
        await db.execute(
            select(BusinessHours)
            .where(BusinessHours.unit_id == unit_id)
            .where(BusinessHours.weekday == pg_weekday)
        )
    ).scalars().all()

    if not bh_rows:
        return AvailabilityOut(
            date=date.isoformat(), barber_id=barber_id, barber_name=barber.name,
            service_duration_min=duration, slots=[],
        )

    bh = max(
        bh_rows,
        key=lambda x: (x.close_time.hour * 60 + x.close_time.minute)
        - (x.open_time.hour * 60 + x.open_time.minute),
    )

    # Gera candidatos de slots no fuso da unidade
    open_dt = datetime(date.year, date.month, date.day, bh.open_time.hour, bh.open_time.minute, tzinfo=tz)
    close_dt = datetime(date.year, date.month, date.day, bh.close_time.hour, bh.close_time.minute, tzinfo=tz)
    last_start = close_dt - timedelta(minutes=duration)

    candidates: List[datetime] = []
    cur = open_dt
    while cur <= last_start:
        candidates.append(cur)
        cur += timedelta(minutes=_SLOT_STEP)

    if not candidates:
        return AvailabilityOut(
            date=date.isoformat(), barber_id=barber_id, barber_name=barber.name,
            service_duration_min=duration, slots=[],
        )

    # Janela UTC do dia para consultas
    day_start_utc = open_dt.astimezone(timezone.utc)
    day_end_utc = (close_dt + timedelta(hours=1)).astimezone(timezone.utc)

    # Agendamentos existentes do barbeiro no dia (não cancelados)
    appts = (
        await db.execute(
            select(Appointment)
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(Appointment.organization_id == org_id)
            .where(AppointmentItem.barber_id == barber_id)
            .where(Appointment.start_at >= day_start_utc)
            .where(Appointment.start_at < day_end_utc)
            .where(Appointment.status != AppointmentStatus.cancelado)
        )
    ).scalars().all()

    # Folgas do barbeiro que cobrem o dia
    time_offs = (
        await db.execute(
            select(TimeOff)
            .where(TimeOff.barber_id == barber_id)
            .where(TimeOff.start_at < day_end_utc)
            .where(TimeOff.end_at > day_start_utc)
        )
    ).scalars().all()

    now_utc = datetime.now(timezone.utc)
    slots: List[Slot] = []

    for slot_start in candidates:
        slot_start_utc = slot_start.astimezone(timezone.utc)
        slot_end_utc = slot_start_utc + timedelta(minutes=duration)

        if slot_start_utc <= now_utc:
            continue
        if any(_overlaps(slot_start_utc, slot_end_utc, a.start_at, a.end_at) for a in appts):
            continue
        if any(_overlaps(slot_start_utc, slot_end_utc, t.start_at, t.end_at) for t in time_offs):
            continue

        local = slot_start.astimezone(tz)
        local_end = local + timedelta(minutes=duration)
        slots.append(
            Slot(
                start=local.strftime("%H:%M"),
                end=local_end.strftime("%H:%M"),
                start_iso=local.isoformat(),
            )
        )

    return AvailabilityOut(
        date=date.isoformat(),
        barber_id=barber_id,
        barber_name=barber.name,
        service_duration_min=duration,
        slots=slots,
    )


# ---------------------------------------------------------------------------
# Agendamentos
# ---------------------------------------------------------------------------


@router.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def create_appointment(body: AppointmentCreateIn, db: BotDB) -> AppointmentOut:
    org_id = settings.bot_organization_id
    unit_id = settings.bot_unit_id

    client = (await db.execute(select(Client).where(Client.id == body.client_id))).scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Cliente não encontrado")

    barber = (await db.execute(select(Barber).where(Barber.id == body.barber_id))).scalar_one_or_none()
    if not barber:
        raise HTTPException(404, "Barbeiro não encontrado")

    svc = (await db.execute(select(Service).where(Service.id == body.service_id))).scalar_one_or_none()
    if not svc:
        raise HTTPException(404, "Serviço não encontrado")

    if body.start_at.tzinfo is None:
        raise HTTPException(422, "start_at deve incluir fuso horário (ex: 2026-06-05T09:00:00-03:00)")

    start_utc = body.start_at.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=svc.default_duration_min)

    if start_utc <= datetime.now(timezone.utc):
        raise HTTPException(422, "Horário já passou")

    conflict = (
        await db.execute(
            select(Appointment.id)
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(AppointmentItem.barber_id == body.barber_id)
            .where(Appointment.status != AppointmentStatus.cancelado)
            .where(Appointment.start_at < end_utc)
            .where(Appointment.end_at > start_utc)
            .limit(1)
        )
    ).first()

    if conflict:
        raise HTTPException(409, "Horário indisponível — conflito de agendamento")

    # display_number sequencial por unidade
    next_num = (
        await db.execute(
            select(func.coalesce(func.max(Appointment.display_number), 0) + 1)
            .where(Appointment.unit_id == unit_id)
        )
    ).scalar_one()

    appt = Appointment(
        organization_id=org_id,
        unit_id=unit_id,
        client_id=body.client_id,
        display_number=next_num,
        start_at=start_utc,
        end_at=end_utc,
        status=AppointmentStatus.agendado,
        booking_channel=ContactChannel.whatsapp,
        total_amount=svc.price,
    )
    db.add(appt)
    await db.flush()

    db.add(
        AppointmentItem(
            appointment_id=appt.id,
            service_id=svc.id,
            barber_id=barber.id,
            price_charged=svc.price,
            duration_minutes=svc.default_duration_min,
        )
    )

    return _appt_out(appt, barber.name, svc.name)


@router.get("/appointments", response_model=List[AppointmentOut])
async def list_appointments(
    phone: str,
    db: BotDB,
) -> list:
    phone = _normalize_phone(phone)
    org_id = settings.bot_organization_id

    client = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()

    if not client:
        return []

    appts = (
        await db.execute(
            select(Appointment)
            .where(Appointment.client_id == client.id)
            .where(Appointment.status == AppointmentStatus.agendado)
            .order_by(Appointment.start_at)
        )
    ).scalars().all()

    results = []
    for appt in appts:
        row = (
            await db.execute(
                select(Barber.name, Service.name)
                .select_from(AppointmentItem)
                .join(Barber, Barber.id == AppointmentItem.barber_id)
                .join(Service, Service.id == AppointmentItem.service_id)
                .where(AppointmentItem.appointment_id == appt.id)
                .limit(1)
            )
        ).first()
        barber_name = row[0] if row else "—"
        svc_name = row[1] if row else "—"
        results.append(_appt_out(appt, barber_name, svc_name))

    return results


@router.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment(appointment_id: int, db: BotDB) -> AppointmentOut:
    appt = (
        await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    ).scalar_one_or_none()

    if not appt:
        raise HTTPException(404, "Agendamento não encontrado")
    if appt.status != AppointmentStatus.agendado:
        raise HTTPException(409, f"Agendamento não pode ser cancelado (status atual: {appt.status.value})")

    appt.status = AppointmentStatus.cancelado

    row = (
        await db.execute(
            select(Barber.name, Service.name)
            .select_from(AppointmentItem)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .join(Service, Service.id == AppointmentItem.service_id)
            .where(AppointmentItem.appointment_id == appt.id)
            .limit(1)
        )
    ).first()

    return _appt_out(appt, row[0] if row else "—", row[1] if row else "—")
