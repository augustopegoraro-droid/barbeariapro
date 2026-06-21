"""Endpoint de agenda com privacidade baseada em role."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dates import local_date
from app.core.rbac import FULL_ACCESS, require_full_access
from app.deps import (
    get_current_user,
    get_tenant_db,
    resolve_current_role,
    resolve_current_role_with_barber,
)
from app.services.calendar_sync import push_appointment
from app.services.scheduling import barber_has_conflict
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BarberService,
    Client,
    Service,
    Unit,
    User,
)

router = APIRouter(prefix="/agenda", tags=["agenda"])


# ─── schemas ─────────────────────────────────────────────────────────────────

class AppointmentOut(BaseModel):
    id: int
    public_id: str
    client_name: Optional[str]
    barber_name: str
    service_name: Optional[str]
    start_at: str
    end_at: str
    status: str
    total_amount: Optional[float]
    is_own: bool


class BarberSimpleOut(BaseModel):
    id: int
    name: str


class ServiceSimpleOut(BaseModel):
    id: int
    name: str
    default_duration_min: int
    price: float
    has_variable_price: bool


class AgendaCriarIn(BaseModel):
    client_id: int
    start_at: datetime
    barber_id: int
    service_id: int
    price_override: Optional[float] = None


class AgendaReagendar(BaseModel):
    start_at: datetime


# ─── helpers ─────────────────────────────────────────────────────────────────

def _appt_out(appt: Appointment, client_name: str, barber_name: str, service_name: str) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        public_id=str(appt.public_id),
        client_name=client_name,
        barber_name=barber_name,
        service_name=service_name,
        start_at=appt.start_at.isoformat(),
        end_at=appt.end_at.isoformat(),
        status=appt.status.value,
        total_amount=float(appt.total_amount),
        is_own=True,
    )


# ─── GET /agenda ──────────────────────────────────────────────────────────────

@router.get("", response_model=list[AppointmentOut])
async def get_agenda(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    date: date = Query(..., description="Data no formato YYYY-MM-DD"),
) -> list[AppointmentOut]:
    role, my_barber_id = await resolve_current_role_with_barber(db, current_user)

    result = await db.execute(
        select(Appointment)
        .where(local_date(Appointment.start_at) == date)
        .options(
            selectinload(Appointment.client),
            selectinload(Appointment.items).selectinload(AppointmentItem.barber),
            selectinload(Appointment.items).selectinload(AppointmentItem.service),
        )
        .order_by(Appointment.start_at)
    )
    appointments = result.scalars().all()

    out: list[AppointmentOut] = []
    for appt in appointments:
        primary = next(
            (i for i in sorted(appt.items, key=lambda x: x.position)),
            None,
        )
        barber_name = primary.barber.name if primary else "—"
        service_name = primary.service.name if primary else None

        if role in FULL_ACCESS:
            is_own = True
        else:
            is_own = any(i.barber_id == my_barber_id for i in appt.items)

        if is_own:
            out.append(AppointmentOut(
                id=appt.id,
                public_id=str(appt.public_id),
                client_name=appt.client.name,
                barber_name=barber_name,
                service_name=service_name,
                start_at=appt.start_at.isoformat(),
                end_at=appt.end_at.isoformat(),
                status=appt.status.value,
                total_amount=float(appt.total_amount),
                is_own=True,
            ))
        else:
            out.append(AppointmentOut(
                id=appt.id,
                public_id=str(appt.public_id),
                client_name=None,
                barber_name=barber_name,
                service_name=None,
                start_at=appt.start_at.isoformat(),
                end_at=appt.end_at.isoformat(),
                status=appt.status.value,
                total_amount=None,
                is_own=False,
            ))

    return out


# ─── GET /agenda/barbers ──────────────────────────────────────────────────────

@router.get("/barbers", response_model=list[BarberSimpleOut])
async def list_barbers_for_agenda(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[BarberSimpleOut]:
    """Lista barbeiros ativos para seleção no modal de novo agendamento."""
    require_full_access(await resolve_current_role(db, current_user))

    barbers = (
        await db.execute(
            select(Barber)
            .where(Barber.deleted_at.is_(None))
            .order_by(Barber.name)
        )
    ).scalars().all()

    return [BarberSimpleOut(id=b.id, name=b.name) for b in barbers]


# ─── GET /agenda/services ─────────────────────────────────────────────────────

@router.get("/services", response_model=list[ServiceSimpleOut])
async def list_services_for_agenda(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    barber_id: Optional[int] = Query(None, description="Filtrar por profissional"),
) -> list[ServiceSimpleOut]:
    """Lista serviços ativos. Com barber_id, retorna apenas os serviços do profissional."""
    require_full_access(await resolve_current_role(db, current_user))

    stmt = (
        select(Service)
        .where(Service.is_active.is_(True))
        .where(Service.deleted_at.is_(None))
        .order_by(Service.name)
    )
    if barber_id is not None:
        stmt = stmt.join(BarberService, BarberService.service_id == Service.id).where(
            BarberService.barber_id == barber_id
        )

    services = (await db.execute(stmt)).scalars().all()

    return [
        ServiceSimpleOut(
            id=s.id,
            name=s.name,
            default_duration_min=s.default_duration_min,
            price=float(s.price),
            has_variable_price=s.has_variable_price,
        )
        for s in services
    ]


# ─── POST /agenda — criar agendamento ────────────────────────────────────────

@router.post("", response_model=AppointmentOut, status_code=http_status.HTTP_201_CREATED)
async def criar_agendamento(
    body: AgendaCriarIn,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AppointmentOut:
    require_full_access(await resolve_current_role(db, current_user))

    # Validar entidades
    client = (await db.execute(select(Client).where(Client.id == body.client_id))).scalar_one_or_none()
    if not client:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    barber = (await db.execute(select(Barber).where(Barber.id == body.barber_id))).scalar_one_or_none()
    if not barber or barber.deleted_at is not None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Barbeiro não encontrado.")

    svc = (await db.execute(select(Service).where(Service.id == body.service_id))).scalar_one_or_none()
    if not svc or not svc.is_active:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Serviço não encontrado ou inativo.")

    # Validar que o profissional executa o serviço
    bs_link = (
        await db.execute(
            select(BarberService)
            .where(BarberService.barber_id == body.barber_id)
            .where(BarberService.service_id == body.service_id)
        )
    ).scalar_one_or_none()
    if not bs_link:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Este profissional não realiza este serviço.",
        )

    # Validar price_override
    if body.price_override is not None:
        if not svc.has_variable_price:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Este serviço não permite alteração de preço.",
            )
        if body.price_override < 0:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "O preço não pode ser negativo.",
            )

    # Normalizar para UTC
    if body.start_at.tzinfo is None:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "start_at deve incluir fuso horário.")
    start_utc = body.start_at.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=svc.default_duration_min)

    # Verificar conflito de barbeiro (agendamento ativo ou folga)
    if await barber_has_conflict(db, body.barber_id, start_utc, end_utc):
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Conflito de horário: barbeiro já tem agendamento ou folga neste período.")

    # Obter unidade padrão da organização
    unit = (
        await db.execute(
            select(Unit)
            .where(Unit.organization_id == current_user.organization_id)
            .where(Unit.deleted_at.is_(None))
            .order_by(Unit.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not unit:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Nenhuma unidade configurada.")

    # display_number sequencial com advisory lock
    await db.execute(text(f"SELECT pg_advisory_xact_lock({unit.id})"))
    next_num = (
        await db.execute(
            select(func.coalesce(func.max(Appointment.display_number), 0) + 1)
            .where(Appointment.unit_id == unit.id)
        )
    ).scalar_one()

    final_price = body.price_override if body.price_override is not None else float(svc.price)

    appt = Appointment(
        organization_id=current_user.organization_id,
        unit_id=unit.id,
        client_id=client.id,
        display_number=next_num,
        start_at=start_utc,
        end_at=end_utc,
        status=AppointmentStatus.agendado,
        booking_channel=None,
        total_amount=final_price,
        created_by_user_id=current_user.id,
    )
    db.add(appt)
    await db.flush()  # popula appt.id e appt.public_id via RETURNING

    # Capturar valores antes do commit (db.refresh não funciona após commit)
    appt_id = appt.id
    public_id = str(appt.public_id)
    start_iso = appt.start_at.isoformat()
    end_iso = appt.end_at.isoformat()
    total = float(appt.total_amount)

    db.add(AppointmentItem(
        appointment_id=appt_id,
        service_id=svc.id,
        barber_id=barber.id,
        price_charged=final_price,
        duration_minutes=svc.default_duration_min,
    ))
    await db.commit()

    background_tasks.add_task(push_appointment, appt_id, current_user.organization_id, "upsert")
    return AppointmentOut(
        id=appt_id,
        public_id=public_id,
        client_name=client.name,
        barber_name=barber.name,
        service_name=svc.name,
        start_at=start_iso,
        end_at=end_iso,
        status="agendado",
        total_amount=total,
        is_own=True,
    )


# ─── PATCH /agenda/{id}/reagendar ────────────────────────────────────────────

@router.patch("/{appt_id}/reagendar", response_model=AppointmentOut)
async def reagendar_agendamento(
    appt_id: Annotated[int, Path(gt=0)],
    body: AgendaReagendar,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AppointmentOut:
    require_full_access(await resolve_current_role(db, current_user))

    appt = (
        await db.execute(
            select(Appointment)
            .where(Appointment.id == appt_id)
            .options(
                selectinload(Appointment.client),
                selectinload(Appointment.items).selectinload(AppointmentItem.barber),
                selectinload(Appointment.items).selectinload(AppointmentItem.service),
            )
        )
    ).scalar_one_or_none()
    if not appt:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Agendamento não encontrado.")
    if appt.status != AppointmentStatus.agendado:
        raise HTTPException(http_status.HTTP_409_CONFLICT, f"Só é possível reagendar agendamentos com status 'agendado'. Status atual: '{appt.status.value}'.")

    if body.start_at.tzinfo is None:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "start_at deve incluir fuso horário.")
    start_utc = body.start_at.astimezone(timezone.utc)

    # Calcular duração original
    duration = int((appt.end_at - appt.start_at).total_seconds() / 60)
    end_utc = start_utc + timedelta(minutes=duration)

    # Verificar conflito para o mesmo barbeiro no novo horário (excluindo o próprio)
    primary_item = next((i for i in sorted(appt.items, key=lambda x: x.position)), None)
    if primary_item:
        if await barber_has_conflict(
            db, primary_item.barber_id, start_utc, end_utc, exclude_appointment_id=appt_id
        ):
            raise HTTPException(http_status.HTTP_409_CONFLICT, "Conflito de horário: barbeiro já tem agendamento ou folga neste período.")

    appt.start_at = start_utc
    appt.end_at = end_utc
    await db.commit()

    background_tasks.add_task(push_appointment, appt_id, current_user.organization_id, "upsert")
    barber_name = primary_item.barber.name if primary_item else "—"
    service_name = primary_item.service.name if primary_item else None
    return _appt_out(appt, appt.client.name, barber_name, service_name)
