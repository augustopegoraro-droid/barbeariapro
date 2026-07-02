"""Endpoint de gestão de equipe: barbeiros, horários e folgas."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status as http_status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_manager_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BarberService,
    BarberUnit,
    BusinessHours,
    Service,
    TimeOff,
    Unit,
    User,
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


# Modelos de trabalho suportados (doc gestaointeligente; migration 0025).
WORK_MODELS = {"clt", "mei", "comissionado", "aluguel_cadeira", "hibrido"}


class BarberOut(BaseModel):
    id: int
    name: str
    specialty: Optional[str]
    commission_pct: float
    work_model: Optional[str] = None
    monthly_cost: float = 0.0
    chair_rent: float = 0.0
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
    require_manager_access(await resolve_current_role(db, current_user))

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
                work_model=b.work_model,
                monthly_cost=float(b.monthly_cost or 0),
                chair_rent=float(b.chair_rent or 0),
                concluido_count=stats[b.id]["concluido"],
                agendado_count=stats[b.id]["agendado"],
                business_hours=hours,
                upcoming_time_off=time_off_by_barber[b.id],
            )
        )

    return EquipeOut(barbers=result)


# ─── escrita: barbeiros ───────────────────────────────────────────────────────

class BarberCreateIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    specialty: Optional[str] = Field(None, max_length=100)
    commission_pct: float = Field(..., ge=0, le=1, description="Fração 0–1 (ex: 0.48)")
    work_model: Optional[str] = Field(None, description="clt|mei|comissionado|aluguel_cadeira|hibrido")
    monthly_cost: float = Field(0, ge=0, description="Custo fixo mensal total (R$)")
    chair_rent: float = Field(0, ge=0, description="Aluguel de cadeira pago à empresa (R$/mês)")

    @field_validator("name", "specialty")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v

    @field_validator("work_model")
    @classmethod
    def valid_work_model(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in WORK_MODELS:
            raise ValueError(f"work_model deve ser um de: {sorted(WORK_MODELS)}")
        return v


class BarberEditIn(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    specialty: Optional[str] = Field(None, max_length=100)
    commission_pct: Optional[float] = Field(None, ge=0, le=1)
    work_model: Optional[str] = None
    monthly_cost: Optional[float] = Field(None, ge=0)
    chair_rent: Optional[float] = Field(None, ge=0)

    @field_validator("name", "specialty")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v

    @field_validator("work_model")
    @classmethod
    def valid_work_model(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in WORK_MODELS:
            raise ValueError(f"work_model deve ser um de: {sorted(WORK_MODELS)}")
        return v


class BarberSimpleOut(BaseModel):
    id: int
    name: str
    specialty: Optional[str]
    commission_pct: float
    work_model: Optional[str] = None
    monthly_cost: float = 0.0
    chair_rent: float = 0.0


async def _require_manager(db: AsyncSession, user: User) -> None:
    require_manager_access(await resolve_current_role(db, user))


async def _load_barber(db: AsyncSession, barber_id: int) -> Barber:
    barber = (
        await db.execute(
            select(Barber)
            .where(Barber.id == barber_id)
            .where(Barber.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if barber is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Barbeiro não encontrado.",
        )
    return barber


def _barber_out(b: Barber) -> BarberSimpleOut:
    return BarberSimpleOut(
        id=b.id, name=b.name, specialty=b.specialty,
        commission_pct=float(b.commission_pct),
        work_model=b.work_model,
        monthly_cost=float(b.monthly_cost or 0),
        chair_rent=float(b.chair_rent or 0),
    )


@router.post("/barbeiros", response_model=BarberSimpleOut, status_code=http_status.HTTP_201_CREATED)
async def criar_barbeiro(
    body: BarberCreateIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> BarberSimpleOut:
    """Cria barbeiro vinculado a todas as unidades e serviços ativos da organização."""
    await _require_manager(db, current_user)

    barber = Barber(
        organization_id=current_user.organization_id,
        name=body.name,
        specialty=body.specialty,
        commission_pct=Decimal(str(body.commission_pct)),
        work_model=body.work_model,
        monthly_cost=Decimal(str(body.monthly_cost)),
        chair_rent=Decimal(str(body.chair_rent)),
    )
    db.add(barber)
    await db.flush()

    unit_ids = (
        await db.execute(select(Unit.id).where(Unit.deleted_at.is_(None)))
    ).scalars().all()
    for uid in unit_ids:
        db.add(BarberUnit(barber_id=barber.id, unit_id=uid))

    service_ids = (
        await db.execute(
            select(Service.id)
            .where(Service.is_active.is_(True))
            .where(Service.deleted_at.is_(None))
        )
    ).scalars().all()
    for sid in service_ids:
        db.add(BarberService(barber_id=barber.id, service_id=sid))

    await db.flush()
    return _barber_out(barber)


@router.patch("/barbeiros/{barber_id}", response_model=BarberSimpleOut)
async def editar_barbeiro(
    body: BarberEditIn,
    barber_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> BarberSimpleOut:
    await _require_manager(db, current_user)
    barber = await _load_barber(db, barber_id)

    if body.name is not None:
        barber.name = body.name
    if body.specialty is not None:
        barber.specialty = body.specialty or None
    if body.commission_pct is not None:
        barber.commission_pct = Decimal(str(body.commission_pct))
    if body.work_model is not None:
        barber.work_model = body.work_model
    if body.monthly_cost is not None:
        barber.monthly_cost = Decimal(str(body.monthly_cost))
    if body.chair_rent is not None:
        barber.chair_rent = Decimal(str(body.chair_rent))

    await db.flush()
    return _barber_out(barber)


@router.patch("/barbeiros/{barber_id}/arquivar", response_model=BarberSimpleOut)
async def arquivar_barbeiro(
    barber_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> BarberSimpleOut:
    """Soft-delete. Bloqueado se houver agendamentos futuros com este barbeiro."""
    await _require_manager(db, current_user)
    barber = await _load_barber(db, barber_id)

    upcoming = (
        await db.execute(
            select(func.count(Appointment.id))
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(AppointmentItem.barber_id == barber_id)
            .where(Appointment.status == AppointmentStatus.agendado)
            .where(Appointment.start_at >= datetime.now(timezone.utc))
        )
    ).scalar_one()
    if upcoming:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Barbeiro tem {upcoming} agendamento(s) futuro(s). Cancele ou reagende antes de arquivar.",
        )

    barber.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return _barber_out(barber)


# ─── escrita: folgas ──────────────────────────────────────────────────────────

class TimeOffCreateIn(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: Optional[str] = Field(None, max_length=200)


@router.post("/barbeiros/{barber_id}/folgas", response_model=TimeOffOut, status_code=http_status.HTTP_201_CREATED)
async def criar_folga(
    body: TimeOffCreateIn,
    barber_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> TimeOffOut:
    await _require_manager(db, current_user)
    await _load_barber(db, barber_id)

    if body.start_at.tzinfo is None or body.end_at.tzinfo is None:
        raise HTTPException(422, "start_at e end_at devem incluir fuso horário")
    if body.end_at <= body.start_at:
        raise HTTPException(422, "end_at deve ser depois de start_at")

    folga = TimeOff(
        barber_id=barber_id,
        start_at=body.start_at,
        end_at=body.end_at,
        reason=body.reason or None,
    )
    db.add(folga)
    await db.flush()

    return TimeOffOut(
        id=folga.id,
        start_at=folga.start_at.isoformat(),
        end_at=folga.end_at.isoformat(),
        reason=folga.reason,
    )


@router.delete("/folgas/{folga_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def remover_folga(
    folga_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    await _require_manager(db, current_user)

    # time_off não tem RLS própria — o join com barbers (RLS) garante o escopo da org
    folga = (
        await db.execute(
            select(TimeOff)
            .join(Barber, Barber.id == TimeOff.barber_id)
            .where(TimeOff.id == folga_id)
        )
    ).scalar_one_or_none()
    if folga is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Folga não encontrada.",
        )

    await db.delete(folga)
    await db.flush()
