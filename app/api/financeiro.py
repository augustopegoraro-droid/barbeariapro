"""Endpoint financeiro: resumo do dia para o painel admin."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import cast, func, select
from sqlalchemy import Date as SADate
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_manager_access, resolve_role
from app.deps import get_current_user, get_tenant_db
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    Client,
    Payment,
    Service,
    User,
    UserUnit,
)
from models.enums import PaymentMethod

router = APIRouter(prefix="/financeiro", tags=["financeiro"])


class MethodOut(BaseModel):
    method: str
    amount: float
    count: int


class BarberOut(BaseModel):
    barber_id: int
    barber_name: str
    appointment_count: int
    revenue: float
    commission: float


class ApptFinanceOut(BaseModel):
    id: int
    client_name: str
    barber_name: str
    service_name: str
    total_amount: float
    start_at: str


class FinanceiroOut(BaseModel):
    date: str
    total_revenue: float
    concluido_count: int
    agendado_count: int
    by_method: list[MethodOut]
    by_barber: list[BarberOut]
    appointments: list[ApptFinanceOut]


@router.get("", response_model=FinanceiroOut)
async def get_financeiro(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    date: date = Query(..., description="Data no formato YYYY-MM-DD"),
) -> FinanceiroOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    role = resolve_role(list(unit_links))
    require_manager_access(role)

    # --- Receita por barbeiro (via appointment_items.price_charged) ----------
    barber_rows = (
        await db.execute(
            select(
                Barber.id,
                Barber.name,
                Barber.commission_pct,
                func.count(Appointment.id.distinct()).label("appt_count"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("revenue"),
            )
            .select_from(AppointmentItem)
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(cast(Appointment.start_at, SADate) == date)
            .group_by(Barber.id, Barber.name, Barber.commission_pct)
            .order_by(func.sum(AppointmentItem.price_charged).desc())
        )
    ).all()

    by_barber = [
        BarberOut(
            barber_id=r.id,
            barber_name=r.name,
            appointment_count=r.appt_count,
            revenue=float(r.revenue),
            commission=float(Decimal(str(r.revenue)) * r.commission_pct),
        )
        for r in barber_rows
    ]

    total_revenue = sum(b.revenue for b in by_barber)

    # --- Contagem de agendamentos do dia -------------------------------------
    counts = (
        await db.execute(
            select(
                Appointment.status,
                func.count(Appointment.id).label("cnt"),
            )
            .where(cast(Appointment.start_at, SADate) == date)
            .group_by(Appointment.status)
        )
    ).all()

    concluido_count = next((r.cnt for r in counts if r.status == AppointmentStatus.concluido), 0)
    agendado_count  = next((r.cnt for r in counts if r.status == AppointmentStatus.agendado), 0)

    # --- Breakdown por método de pagamento (tabela payments) -----------------
    method_rows = (
        await db.execute(
            select(
                Payment.method,
                func.sum(Payment.amount + func.coalesce(Payment.tip_amount, 0)).label("total"),
                func.count(Payment.id).label("cnt"),
            )
            .where(cast(Payment.paid_at, SADate) == date)
            .group_by(Payment.method)
            .order_by(func.sum(Payment.amount).desc())
        )
    ).all()

    by_method = [
        MethodOut(method=r.method.value, amount=float(r.total), count=r.cnt)
        for r in method_rows
    ]

    # --- Lista de agendamentos concluídos com detalhes -----------------------
    appt_rows = (
        await db.execute(
            select(
                Appointment.id,
                Appointment.total_amount,
                Appointment.start_at,
                Client.name.label("client_name"),
                Barber.name.label("barber_name"),
                Service.name.label("service_name"),
            )
            .join(Client, Client.id == Appointment.client_id)
            .outerjoin(
                AppointmentItem,
                (AppointmentItem.appointment_id == Appointment.id)
                & (AppointmentItem.position == 1),
            )
            .outerjoin(Barber, Barber.id == AppointmentItem.barber_id)
            .outerjoin(Service, Service.id == AppointmentItem.service_id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(cast(Appointment.start_at, SADate) == date)
            .order_by(Appointment.start_at)
        )
    ).all()

    appointments = [
        ApptFinanceOut(
            id=r.id,
            client_name=r.client_name,
            barber_name=r.barber_name or "—",
            service_name=r.service_name or "—",
            total_amount=float(r.total_amount),
            start_at=r.start_at.isoformat(),
        )
        for r in appt_rows
    ]

    return FinanceiroOut(
        date=date.isoformat(),
        total_revenue=total_revenue,
        concluido_count=concluido_count,
        agendado_count=agendado_count,
        by_method=by_method,
        by_barber=by_barber,
        appointments=appointments,
    )
