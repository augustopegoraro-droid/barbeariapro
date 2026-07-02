"""Dashboard do Gestor (camada JWT) — tools de gestão para o frontend.

Mesma camada de cálculo das tools do bot (`app/services/management.py`), aqui
exposta com autenticação JWT + RBAC (owner/manager). Recepção fica de fora de
dados financeiros (`require_manager_access`). Multi-tenant real via RLS do token.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import today_local
from app.core.rbac import require_manager_access
from app.deps import get_bot_db, get_current_user, get_tenant_db, resolve_current_role
from app.services import gestor_notify as _notify
from app.services import reactivation as _reactivation
from app.services.management import (
    agenda_gaps,
    ai_generated_revenue,
    barber_ranking,
    financial_summary,
    inactive_clients,
    mrr,
    payroll_summary,
    recurring_coverage,
    resolve_period,
)
from models import Unit, User

router = APIRouter(prefix="/admin/gestor", tags=["gestor"])
internal_router = APIRouter(prefix="/internal/gestor", tags=["gestor-internal"])
BotDB = Annotated[AsyncSession, Depends(get_bot_db)]


async def _require_manager(db: AsyncSession, user: User) -> None:
    require_manager_access(await resolve_current_role(db, user))


async def _primary_unit_id(db: AsyncSession) -> Optional[int]:
    """Unidade primária do tenant (RLS) — a mais antiga. Base p/ buracos/IA."""
    return (
        await db.execute(
            select(Unit.id).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1)
        )
    ).scalar_one_or_none()


# ─── schemas ──────────────────────────────────────────────────────────────────

class MethodOut(BaseModel):
    method: str
    amount: float
    count: int


class FinanceiroOut(BaseModel):
    period: str
    date_from: str
    date_to: str
    revenue: float
    commissions: float
    expenses: float
    net: float
    appointment_count: int
    by_method: list[MethodOut]


class BarberOut(BaseModel):
    barber_id: int
    barber_name: str
    appointment_count: int
    revenue: float
    ticket_medio: float
    commission: float


class RankingOut(BaseModel):
    period: str
    date_from: str
    date_to: str
    barbers: list[BarberOut]


# ─── rotas ────────────────────────────────────────────────────────────────────

@router.get("/financeiro", response_model=FinanceiroOut)
async def financeiro(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    period: Optional[str] = Query(None, description="hoje|ontem|semana|mes"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
) -> FinanceiroOut:
    """Resumo financeiro do período (receita, comissões, despesas, líquido)."""
    await _require_manager(db, current_user)
    df, dt, label = resolve_period(period, date_from, date_to)
    data = await financial_summary(db, df, dt)
    return FinanceiroOut(period=label, **data)


@router.get("/ranking", response_model=RankingOut)
async def ranking(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    period: Optional[str] = Query(None, description="hoje|ontem|semana|mes"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
) -> RankingOut:
    """Ranking de produção por barbeiro no período."""
    await _require_manager(db, current_user)
    df, dt, label = resolve_period(period, date_from, date_to)
    barbers = await barber_ranking(db, df, dt)
    return RankingOut(
        period=label, date_from=df.isoformat(), date_to=dt.isoformat(), barbers=barbers
    )


# ─── Fase B — inativos, buracos, faturamento-IA, MRR ──────────────────────────

class InativoOut(BaseModel):
    client_id: int
    name: str
    phone: Optional[str] = None
    days_since_last_visit: Optional[int] = None
    visit_count: int = 0
    status: Optional[str] = None
    preferred_barber: Optional[str] = None


class InativosOut(BaseModel):
    count: int
    clients: list[InativoOut]


@router.get("/inativos", response_model=InativosOut)
async def inativos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    days: Optional[int] = Query(None, ge=1, description="Sem dias: usa status em_risco/inativo"),
    limit: int = Query(50, ge=1, le=200),
) -> InativosOut:
    """Clientes parados, candidatos a reativação."""
    await _require_manager(db, current_user)
    clients = await inactive_clients(db, days=days, limit=limit)
    return InativosOut(count=len(clients), clients=clients)


class DisparoOut(BaseModel):
    sent: int
    skipped: int
    total_targets: int


@router.post("/inativos/disparar", response_model=DisparoOut)
async def inativos_disparar(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> DisparoOut:
    """Dispara a campanha de reativação (respeita cooldown e opt-out)."""
    await _require_manager(db, current_user)
    result = await _reactivation.run(
        org_id=current_user.organization_id, session=db
    )
    return DisparoOut(**result)


class WindowOut(BaseModel):
    start: str
    end: str


class BuracoBarberOut(BaseModel):
    barber_id: int
    barber_name: str
    idle_min: int
    free_windows: list[WindowOut]


class BuracosOut(BaseModel):
    date: str
    barbers: list[BuracoBarberOut]


@router.get("/buracos", response_model=BuracosOut)
async def buracos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    date_param: Optional[date] = Query(None, alias="date", description="Default: hoje"),
) -> BuracosOut:
    """Janelas ociosas por barbeiro na data (default hoje)."""
    await _require_manager(db, current_user)
    target = date_param or today_local()
    unit_id = await _primary_unit_id(db)
    barbers = await agenda_gaps(db, target, unit_id) if unit_id else []
    return BuracosOut(date=target.isoformat(), barbers=barbers)


class IaFaturamentoOut(BaseModel):
    date_from: str
    date_to: str
    appointments: int
    revenue: float
    leads_after_hours: int


@router.get("/ia-faturamento", response_model=IaFaturamentoOut)
async def ia_faturamento(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    period: Optional[str] = Query(None, description="hoje|ontem|semana|mes"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
) -> IaFaturamentoOut:
    """Resultado atribuível ao bot: agendamentos/receita via WhatsApp + leads fora
    do horário comercial."""
    await _require_manager(db, current_user)
    df, dt, _ = resolve_period(period, date_from, date_to)
    unit_id = await _primary_unit_id(db)
    data = await ai_generated_revenue(db, df, dt, unit_id)
    return IaFaturamentoOut(**data)


class MrrOut(BaseModel):
    active_count: int
    mrr: float
    expiring_30d: int


@router.get("/mrr", response_model=MrrOut)
async def mrr_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MrrOut:
    """Receita recorrente das assinaturas vigentes + quantas vencem em 30 dias."""
    await _require_manager(db, current_user)
    return MrrOut(**await mrr(db))


# ─── folha / gestão de equipe (doc gestaointeligente) ─────────────────────────

class FolhaMemberOut(BaseModel):
    barber_id: int
    barber_name: str
    work_model: str
    monthly_cost: float
    commission: float
    chair_rent: float
    total_cost: float


class CoverageOut(BaseModel):
    mrr: float
    active_subscriptions: int
    fixed_payroll: float
    chair_rent_income: float
    net_fixed_payroll: float
    covered: bool
    coverage_pct: Optional[float] = None
    surplus: float


class FolhaOut(BaseModel):
    period: str
    date_from: str
    date_to: str
    team: list[FolhaMemberOut]
    fixed_total: float
    commissions_total: float
    chair_rent_income: float
    payroll_total: float
    net_cost: float
    coverage: CoverageOut


@router.get("/folha", response_model=FolhaOut)
async def folha(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    period: Optional[str] = Query(None, description="hoje|ontem|semana|mes (comissões)"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
) -> FolhaOut:
    """Folha da equipe (fixo + comissões − aluguel de cadeira) e a resposta à
    pergunta do doc de gestão: **a receita recorrente cobre a folha fixa?**"""
    await _require_manager(db, current_user)
    df, dt, label = resolve_period(period or "mes", date_from, date_to)
    data = await payroll_summary(db, df, dt)
    coverage = await recurring_coverage(db)
    return FolhaOut(
        period=label,
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
        coverage=CoverageOut(**coverage),
        **data,
    )


# ─── Fase C — push proativo (cron n8n, auth X-Bot-Token) ──────────────────────

class DigestRunOut(BaseModel):
    recipients: int
    sent: int
    digest: dict


@internal_router.post("/resumo-diario", response_model=DigestRunOut)
async def run_daily_digest(db: BotDB) -> DigestRunOut:
    """Calcula e envia o resumo diário aos gestores. Cron noturno do n8n."""
    result = await _notify.send_daily_digest(db, today_local())
    return DigestRunOut(**result)


class AlertsRunOut(BaseModel):
    alerts: int
    recipients: int
    sent: int


@internal_router.post("/alertas", response_model=AlertsRunOut)
async def run_alerts(db: BotDB) -> AlertsRunOut:
    """Avalia alertas de meta/queda e envia se houver. Cron do n8n em horário comercial."""
    result = await _notify.send_alerts(db, today_local())
    return AlertsRunOut(**result)
