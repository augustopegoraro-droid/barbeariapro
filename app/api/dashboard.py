"""Dashboard de métricas consolidadas."""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import local_date, local_tz, today_local
from app.core.rbac import require_full_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BusinessHours,
    Client,
    ClientLoyalty,
    Lead,
    Service,
    Unit,
    User,
)
from models.enums import LeadStage, LoyaltyNivel, LoyaltyStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Period = Literal["hoje", "7d", "30d", "mes"]


def _period_range(period: Period) -> tuple[date, date]:
    today = today_local()
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
    require_full_access(await resolve_current_role(db, current_user))

    date_from, date_to = _period_range(period)

    # ── 1. Status breakdown dos agendamentos no período ──────────────────────
    status_rows = (
        await db.execute(
            select(Appointment.status, func.count(Appointment.id).label("cnt"))
            .where(
                local_date(Appointment.start_at) >= date_from,
                local_date(Appointment.start_at) <= date_to,
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
                local_date(Appointment.start_at) >= date_from,
                local_date(Appointment.start_at) <= date_to,
            )
        )
    ).one()

    total_revenue = float(rev_rows.rev)
    avg_ticket = total_revenue / concluido if concluido > 0 else 0.0

    # ── 3. Série diária de receita ────────────────────────────────────────────
    daily_rows = (
        await db.execute(
            select(
                local_date(Appointment.start_at).label("day"),
                func.count(Appointment.id.distinct()).label("cnt"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("rev"),
            )
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(
                Appointment.status == AppointmentStatus.concluido,
                local_date(Appointment.start_at) >= date_from,
                local_date(Appointment.start_at) <= date_to,
            )
            .group_by(local_date(Appointment.start_at))
            .order_by(local_date(Appointment.start_at))
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
                local_date(Appointment.start_at) >= date_from,
                local_date(Appointment.start_at) <= date_to,
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
                local_date(Appointment.start_at) >= date_from,
                local_date(Appointment.start_at) <= date_to,
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
                local_date(Appointment.start_at) >= date_from,
                local_date(Appointment.start_at) <= date_to,
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
                local_date(Client.created_at) >= date_from,
                local_date(Client.created_at) <= date_to,
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


# ═══════════════════════════════════════════════════════════════════════════
# Métricas operacionais (CRM/IA): leads, serviços realizados, picos de demanda
# e fluxo comercial vs fora do horário comercial.
# ═══════════════════════════════════════════════════════════════════════════

_STAGE_ORDER: tuple[LeadStage, ...] = (
    LeadStage.novo_contato,
    LeadStage.conversando,
    LeadStage.agendado,
    LeadStage.concluido,
    LeadStage.perdido,
)


class DailyCount(BaseModel):
    date: str
    count: int


class StageCount(BaseModel):
    stage: str
    count: int


class DemandHour(BaseModel):
    hour: int
    count: int


class FluxoComercial(BaseModel):
    """Volume de leads dentro vs fora do horário comercial (horas da unidade)."""

    comercial: int
    fora: int
    comercial_pct: float
    fora_pct: float


class OperacionalOut(BaseModel):
    period: str
    date_from: str
    date_to: str
    leads_total: int
    leads_por_dia: list[DailyCount]
    leads_por_estagio: list[StageCount]
    servicos_realizados: list[ServiceRank]
    picos_demanda: list[DemandHour]
    fluxo: FluxoComercial


async def _business_hour_windows(db: AsyncSession) -> dict[int, list[tuple[time, time]]]:
    """Janelas de horário comercial por dia da semana (0=dom..6=sáb).

    Escopado ao tenant via join com `units` (que tem RLS); `business_hours` não
    tem coluna de organização. Sem horários cadastrados, assume seg–sáb 9h–19h.
    """
    rows = (
        await db.execute(
            select(
                BusinessHours.weekday,
                BusinessHours.open_time,
                BusinessHours.close_time,
            )
            .join(Unit, Unit.id == BusinessHours.unit_id)
            .where(Unit.deleted_at.is_(None))
        )
    ).all()
    windows: dict[int, list[tuple[time, time]]] = {}
    for r in rows:
        windows.setdefault(r.weekday, []).append((r.open_time, r.close_time))
    if not windows:
        windows = {wd: [(time(9, 0), time(19, 0))] for wd in range(1, 7)}
    return windows


@router.get("/operacional", response_model=OperacionalOut)
async def get_operacional(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    period: Period = Query("30d"),
) -> OperacionalOut:
    require_full_access(await resolve_current_role(db, current_user))
    date_from, date_to = _period_range(period)

    # ── 1. Volume de leads por dia (criação) ──────────────────────────────────
    lead_rows = (
        await db.execute(
            select(
                local_date(Lead.created_at).label("day"),
                func.count(Lead.id).label("cnt"),
            )
            .where(
                local_date(Lead.created_at) >= date_from,
                local_date(Lead.created_at) <= date_to,
            )
            .group_by(local_date(Lead.created_at))
        )
    ).all()
    lead_map = {r.day: r.cnt for r in lead_rows}
    leads_por_dia: list[DailyCount] = []
    cursor = date_from
    while cursor <= date_to:
        leads_por_dia.append(
            DailyCount(date=cursor.isoformat(), count=lead_map.get(cursor, 0))
        )
        cursor += timedelta(days=1)
    leads_total = sum(lead_map.values())

    # ── 2. Leads por estágio (snapshot atual do funil) ────────────────────────
    stage_rows = (
        await db.execute(
            select(Lead.stage, func.count(Lead.id).label("cnt")).group_by(Lead.stage)
        )
    ).all()
    stage_map = {r.stage: r.cnt for r in stage_rows}
    leads_por_estagio = [
        StageCount(stage=s.value, count=stage_map.get(s, 0)) for s in _STAGE_ORDER
    ]

    # ── 3. Serviços realizados (concluídos no período) — lista completa ───────
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
                local_date(Appointment.start_at) >= date_from,
                local_date(Appointment.start_at) <= date_to,
            )
            .group_by(Service.id, Service.name, Service.category)
            .order_by(func.count(AppointmentItem.id).desc())
        )
    ).all()
    servicos_realizados = [
        ServiceRank(
            service_id=r.id,
            name=r.name,
            category=r.category.value,
            count=r.cnt,
            revenue=float(r.rev),
        )
        for r in svc_rows
    ]

    # ── 4. Picos de demanda (hora local dos agendamentos) ─────────────────────
    hour_expr = func.extract(
        "hour", func.timezone(settings.app_timezone, Appointment.start_at)
    )
    demand_rows = (
        await db.execute(
            select(hour_expr.label("h"), func.count(Appointment.id.distinct()).label("cnt"))
            .where(
                local_date(Appointment.start_at) >= date_from,
                local_date(Appointment.start_at) <= date_to,
            )
            .group_by(hour_expr)
            .order_by(hour_expr)
        )
    ).all()
    picos_demanda = [DemandHour(hour=int(r.h), count=r.cnt) for r in demand_rows]

    # ── 5. Fluxo comercial vs fora do horário comercial (leads do período) ────
    windows = await _business_hour_windows(db)
    lead_created_rows = (
        await db.execute(
            select(Lead.created_at).where(
                local_date(Lead.created_at) >= date_from,
                local_date(Lead.created_at) <= date_to,
            )
        )
    ).scalars().all()
    tz = local_tz()
    comercial = 0
    fora = 0
    for created in lead_created_rows:
        loc = created.astimezone(tz)
        weekday = loc.isoweekday() % 7  # 0=dom..6=sáb (igual ao business_hours)
        t = loc.time()
        in_hours = any(o <= t < c for (o, c) in windows.get(weekday, []))
        if in_hours:
            comercial += 1
        else:
            fora += 1
    total_fluxo = comercial + fora
    fluxo = FluxoComercial(
        comercial=comercial,
        fora=fora,
        comercial_pct=round(comercial / total_fluxo * 100, 1) if total_fluxo else 0.0,
        fora_pct=round(fora / total_fluxo * 100, 1) if total_fluxo else 0.0,
    )

    return OperacionalOut(
        period=period,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        leads_total=leads_total,
        leads_por_dia=leads_por_dia,
        leads_por_estagio=leads_por_estagio,
        servicos_realizados=servicos_realizados,
        picos_demanda=picos_demanda,
        fluxo=fluxo,
    )
