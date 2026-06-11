"""Dashboard de métricas consolidadas."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import cast, func, select
from sqlalchemy import Date as SADate
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_full_access, resolve_role
from app.deps import get_current_user, get_tenant_db
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    Client,
    ClientLoyalty,
    Service,
    User,
    UserUnit,
)
from models.enums import LoyaltyNivel, LoyaltyStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Period = Literal["hoje", "7d", "30d", "mes"]


def _period_range(period: Period) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    if period == "hoje":
        return today, today
    if period == "7d":
        return today - timedelta(days=6), today
    if period == "30d":
        return today - timedelta(days=29), today
    # mes
    return today.replace(day=1), today


# ─── response schema ─────────────────────────────────────────────────────────

class DailyPoint(BaseModel):
    date: str
    revenue: float
    count: int


class BarberRank(BaseModel):
    barber_id: int
    name: str
    concluido_count: int
    revenue: float
    commission: float
    conversion_pct: float   # concluidos / (concluidos + cancelados + faltou) * 100


class ServiceRank(BaseModel):
    service_id: int
    name: str
    category: str
    count: int
    revenue: float


class LoyaltySlice(BaseModel):
    label: str
    count: int


class DashboardOut(BaseModel):
    period: str
    date_from: str
    date_to: str
    # receita
    total_revenue: float
    avg_ticket: float
    # ocupação
    total_appointments: int
    concluido_count: int
    agendado_count: int
    cancelado_count: int
    faltou_count: int
    # clientes
    new_clients: int
    total_clients: int
    at_risk_count: int
    # série diária
    daily: list[DailyPoint]
    # rankings
    barbers: list[BarberRank]
    top_services: list[ServiceRank]
    loyalty_nivel: list[LoyaltySlice]
    loyalty_status: list[LoyaltySlice]


@router.get("", response_model=DashboardOut)
async def get_dashboard(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    period: Period = Query("30d"),
) -> DashboardOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    require_full_access(resolve_role(list(unit_links)))

    date_from, date_to = _period_range(period)

    # ── 1. Status breakdown dos agendamentos no período ──────────────────────
    status_rows = (
        await db.execute(
            select(Appointment.status, func.count(Appointment.id).label("cnt"))
            .where(
                cast(Appointment.start_at, SADate) >= date_from,
                cast(Appointment.start_at, SADate) <= date_to,
            )
            .group_by(Appointment.status)
        )
    ).all()

    counts = {r.status.value: r.cnt for r in status_rows}
    concluido  = counts.get("concluido", 0)
    agendado   = counts.get("agendado", 0)
    cancelado  = counts.get("cancelado", 0)
    faltou     = counts.get("faltou", 0)
    total_appts = concluido + agendado + cancelado + faltou

    # ── 2. Receita do período (via appointment_items, apenas concluidos) ─────
    rev_rows = (
        await db.execute(
            select(func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("rev"))
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(
                Appointment.status == AppointmentStatus.concluido,
                cast(Appointment.start_at, SADate) >= date_from,
                cast(Appointment.start_at, SADate) <= date_to,
            )
        )
    ).one()

    total_revenue = float(rev_rows.rev)
    avg_ticket = total_revenue / concluido if concluido > 0 else 0.0

    # ── 3. Série diária de receita ────────────────────────────────────────────
    daily_rows = (
        await db.execute(
            select(
                cast(Appointment.start_at, SADate).label("day"),
                func.count(Appointment.id.distinct()).label("cnt"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("rev"),
            )
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(
                Appointment.status == AppointmentStatus.concluido,
                cast(Appointment.start_at, SADate) >= date_from,
                cast(Appointment.start_at, SADate) <= date_to,
            )
            .group_by(cast(Appointment.start_at, SADate))
            .order_by(cast(Appointment.start_at, SADate))
        )
    ).all()

    # preencher dias sem receita com zero
    daily_map = {r.day: (r.cnt, float(r.rev)) for r in daily_rows}
    daily: list[DailyPoint] = []
    cursor = date_from
    while cursor <= date_to:
        cnt, rev = daily_map.get(cursor, (0, 0.0))
        daily.append(DailyPoint(date=cursor.isoformat(), revenue=rev, count=cnt))
        cursor += timedelta(days=1)

    # ── 4. Ranking de barbeiros ───────────────────────────────────────────────
    barber_rev_rows = (
        await db.execute(
            select(
                Barber.id,
                Barber.name,
                Barber.commission_pct,
                func.count(Appointment.id.distinct()).label("concluidos"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("revenue"),
            )
            .select_from(AppointmentItem)
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .where(
                Appointment.status == AppointmentStatus.concluido,
                cast(Appointment.start_at, SADate) >= date_from,
                cast(Appointment.start_at, SADate) <= date_to,
            )
            .group_by(Barber.id, Barber.name, Barber.commission_pct)
            .order_by(func.sum(AppointmentItem.price_charged).desc())
        )
    ).all()

    # taxa de conversão: concluidos / (concluidos + cancelados + faltou) por barbeiro
    conv_rows = (
        await db.execute(
            select(
                AppointmentItem.barber_id,
                Appointment.status,
                func.count(Appointment.id.distinct()).label("cnt"),
            )
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(
                cast(Appointment.start_at, SADate) >= date_from,
                cast(Appointment.start_at, SADate) <= date_to,
                Appointment.status.in_([
                    AppointmentStatus.concluido,
                    AppointmentStatus.cancelado,
                    AppointmentStatus.faltou,
                ]),
            )
            .group_by(AppointmentItem.barber_id, Appointment.status)
        )
    ).all()

    conv_map: dict[int, dict[str, int]] = {}
    for r in conv_rows:
        conv_map.setdefault(r.barber_id, {})[r.status.value] = r.cnt

    barbers: list[BarberRank] = []
    for r in barber_rev_rows:
        cm = conv_map.get(r.id, {})
        done = cm.get("concluido", 0)
        total_finished = done + cm.get("cancelado", 0) + cm.get("faltou", 0)
        conv_pct = (done / total_finished * 100) if total_finished > 0 else 0.0
        barbers.append(BarberRank(
            barber_id=r.id,
            name=r.name,
            concluido_count=r.concluidos,
            revenue=float(r.revenue),
            commission=float(Decimal(str(r.revenue)) * r.commission_pct),
            conversion_pct=round(conv_pct, 1),
        ))

    # ── 5. Top serviços ───────────────────────────────────────────────────────
    svc_rows = (
        await db.execute(
            select(
                Service.id,
                Service.name,
                Service.category,
                func.count(AppointmentItem.id).label("cnt"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("rev"),
            )
            .select_from(AppointmentItem)
            .join(Service, Service.id == AppointmentItem.service_id)
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(
                Appointment.status == AppointmentStatus.concluido,
                cast(Appointment.start_at, SADate) >= date_from,
                cast(Appointment.start_at, SADate) <= date_to,
            )
            .group_by(Service.id, Service.name, Service.category)
            .order_by(func.count(AppointmentItem.id).desc())
            .limit(5)
        )
    ).all()

    top_services = [
        ServiceRank(
            service_id=r.id,
            name=r.name,
            category=r.category.value,
            count=r.cnt,
            revenue=float(r.rev),
        )
        for r in svc_rows
    ]

    # ── 6. Clientes novos no período ──────────────────────────────────────────
    new_clients = (
        await db.execute(
            select(func.count(Client.id))
            .where(
                Client.deleted_at.is_(None),
                cast(Client.created_at, SADate) >= date_from,
                cast(Client.created_at, SADate) <= date_to,
            )
        )
    ).scalar_one()

    total_clients = (
        await db.execute(
            select(func.count(Client.id)).where(Client.deleted_at.is_(None))
        )
    ).scalar_one()

    # ── 7. Loyalty breakdown (snapshot atual, sem filtro de período) ──────────
    nivel_rows = (
        await db.execute(
            select(ClientLoyalty.nivel, func.count(ClientLoyalty.id).label("cnt"))
            .group_by(ClientLoyalty.nivel)
        )
    ).all()

    nivel_order = {LoyaltyNivel.vip: 0, LoyaltyNivel.fiel: 1, LoyaltyNivel.ativo: 2, LoyaltyNivel.novo: 3}
    nivel_rows_sorted = sorted(nivel_rows, key=lambda r: nivel_order.get(r.nivel, 9))
    loyalty_nivel = [LoyaltySlice(label=r.nivel.value, count=r.cnt) for r in nivel_rows_sorted]

    status_loyalty_rows = (
        await db.execute(
            select(ClientLoyalty.status, func.count(ClientLoyalty.id).label("cnt"))
            .group_by(ClientLoyalty.status)
        )
    ).all()

    status_order = {LoyaltyStatus.ativo: 0, LoyaltyStatus.em_risco: 1, LoyaltyStatus.inativo: 2}
    status_loyalty_sorted = sorted(status_loyalty_rows, key=lambda r: status_order.get(r.status, 9))
    loyalty_status = [LoyaltySlice(label=r.status.value, count=r.cnt) for r in status_loyalty_sorted]

    at_risk = sum(r.cnt for r in status_loyalty_rows if r.status == LoyaltyStatus.em_risco)

    return DashboardOut(
        period=period,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        total_revenue=total_revenue,
        avg_ticket=round(avg_ticket, 2),
        total_appointments=total_appts,
        concluido_count=concluido,
        agendado_count=agendado,
        cancelado_count=cancelado,
        faltou_count=faltou,
        new_clients=new_clients,
        total_clients=total_clients,
        at_risk_count=at_risk,
        daily=daily,
        barbers=barbers,
        top_services=top_services,
        loyalty_nivel=loyalty_nivel,
        loyalty_status=loyalty_status,
    )
