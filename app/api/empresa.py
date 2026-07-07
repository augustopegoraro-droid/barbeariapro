"""API de configuração da empresa — acesso restrito a owner e manager.

Centraliza o cadastro do negócio para a tela /admin/empresa:
- dados cadastrais da organização (razão social, CNPJ, contato, logo);
- endereço/timezone e horário de funcionamento da unidade principal;
- leitura do plano/assinatura SaaS (read-only).

Premissa atual: cada organização opera com UMA unidade ativa (cliente âncora).
Usamos a primeira unidade não deletada como "unidade principal". Multi-unidade
fica para uma evolução futura.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette import status as http_status

from app.authz import require_permission
from app.core.rbac import require_manager_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from models import Barber, BusinessHours, Organization, Subscription, Unit

router = APIRouter(tags=["empresa"])

WEEKDAYS = 7  # 0=domingo ... 6=sábado


# ── Schemas ────────────────────────────────────────────────────────────────────

class OrganizationOut(BaseModel):
    id: int
    name: str
    legal_name: Optional[str] = None
    cnpj: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    instagram: Optional[str] = None
    logo_url: Optional[str] = None
    monthly_revenue_goal: Optional[float] = None

    class Config:
        from_attributes = True


class UnitOut(BaseModel):
    id: int
    name: str
    address: Optional[str] = None
    timezone: str

    class Config:
        from_attributes = True


class BusinessHourSlot(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    open_time: time
    close_time: time


class PlanOut(BaseModel):
    name: str
    price_month: float
    max_units: int
    max_barbers: int


class SubscriptionOut(BaseModel):
    status: str
    current_period_start: datetime
    current_period_end: datetime
    plan: PlanOut


class UsageOut(BaseModel):
    barbers: int
    units: int


class EmpresaOut(BaseModel):
    organization: OrganizationOut
    unit: Optional[UnitOut] = None
    business_hours: list[BusinessHourSlot]
    subscription: Optional[SubscriptionOut] = None
    usage: UsageOut


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    legal_name: Optional[str] = Field(None, max_length=160)
    cnpj: Optional[str] = Field(None, max_length=20)
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=160)
    website: Optional[str] = Field(None, max_length=200)
    instagram: Optional[str] = Field(None, max_length=120)
    logo_url: Optional[str] = Field(None, max_length=500)
    monthly_revenue_goal: Optional[float] = Field(None, ge=0, description="Meta de faturamento mensal (R$); null limpa")


class UnitUpdate(BaseModel):
    address: Optional[str] = Field(None, max_length=300)
    timezone: Optional[str] = Field(None, min_length=1, max_length=60)


class HorariosUpdate(BaseModel):
    slots: list[BusinessHourSlot]


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _primary_unit(db: AsyncSession) -> Optional[Unit]:
    """Unidade principal da org (mais antiga ativa). RLS já escopa por tenant."""
    return (
        await db.execute(
            select(Unit)
            .where(Unit.deleted_at.is_(None))
            .order_by(Unit.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def _require_manager(db: AsyncSession, current_user) -> None:
    await require_permission(db, current_user, "settings.company.manage")


def _enum_value(value) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


# ── GET /empresa ──────────────────────────────────────────────────────────────

@router.get("/empresa", response_model=EmpresaOut)
async def obter_empresa(
    db: AsyncSession = Depends(get_tenant_db),
    current_user=Depends(get_current_user),
):
    await _require_manager(db, current_user)

    org = (
        await db.execute(
            select(Organization).where(Organization.id == current_user.organization_id)
        )
    ).scalar_one()

    unit = await _primary_unit(db)

    hours: list[BusinessHourSlot] = []
    if unit is not None:
        rows = (
            await db.execute(
                select(BusinessHours)
                .where(BusinessHours.unit_id == unit.id)
                .order_by(BusinessHours.weekday, BusinessHours.open_time)
            )
        ).scalars().all()
        hours = [
            BusinessHourSlot(
                weekday=h.weekday, open_time=h.open_time, close_time=h.close_time
            )
            for h in rows
        ]

    sub_row = (
        await db.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .where(Subscription.organization_id == current_user.organization_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    subscription: Optional[SubscriptionOut] = None
    if sub_row is not None:
        plan = sub_row.plan
        subscription = SubscriptionOut(
            status=_enum_value(sub_row.status),
            current_period_start=sub_row.current_period_start,
            current_period_end=sub_row.current_period_end,
            plan=PlanOut(
                name=plan.name,
                price_month=float(plan.price_month),
                max_units=plan.max_units,
                max_barbers=plan.max_barbers,
            ),
        )

    barbers_count = (
        await db.execute(
            select(func.count()).select_from(Barber).where(Barber.deleted_at.is_(None))
        )
    ).scalar_one()
    units_count = (
        await db.execute(
            select(func.count()).select_from(Unit).where(Unit.deleted_at.is_(None))
        )
    ).scalar_one()

    return EmpresaOut(
        organization=OrganizationOut.model_validate(org),
        unit=UnitOut.model_validate(unit) if unit is not None else None,
        business_hours=hours,
        subscription=subscription,
        usage=UsageOut(barbers=barbers_count, units=units_count),
    )


# ── PATCH /empresa ────────────────────────────────────────────────────────────

@router.patch("/empresa", response_model=OrganizationOut)
async def atualizar_empresa(
    body: OrganizationUpdate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user=Depends(get_current_user),
):
    await _require_manager(db, current_user)

    org = (
        await db.execute(
            select(Organization).where(Organization.id == current_user.organization_id)
        )
    ).scalar_one()

    for field, value in body.model_dump(exclude_unset=True).items():
        # Strings vazias viram NULL (limpa o campo); demais valores normalizam o trim.
        if isinstance(value, str):
            value = value.strip() or None
        setattr(org, field, value)

    await db.flush()
    out = OrganizationOut.model_validate(org)
    await db.commit()
    return out


# ── PATCH /empresa/unidade ────────────────────────────────────────────────────

@router.patch("/empresa/unidade", response_model=UnitOut)
async def atualizar_unidade(
    body: UnitUpdate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user=Depends(get_current_user),
):
    await _require_manager(db, current_user)

    unit = await _primary_unit(db)
    if unit is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Nenhuma unidade cadastrada.",
        )

    data = body.model_dump(exclude_unset=True)
    if "address" in data:
        addr = data["address"]
        unit.address = addr.strip() or None if isinstance(addr, str) else addr
    if "timezone" in data and data["timezone"]:
        unit.timezone = data["timezone"].strip()

    await db.flush()
    out = UnitOut.model_validate(unit)
    await db.commit()
    return out


# ── PUT /empresa/horarios ─────────────────────────────────────────────────────

@router.put("/empresa/horarios", response_model=list[BusinessHourSlot])
async def substituir_horarios(
    body: HorariosUpdate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user=Depends(get_current_user),
):
    """Replace-all da grade semanal da unidade principal."""
    await _require_manager(db, current_user)

    unit = await _primary_unit(db)
    if unit is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Nenhuma unidade cadastrada.",
        )

    # Validação amigável (o banco também tem CheckConstraint bh_time_valid).
    seen: set[tuple[int, time]] = set()
    for slot in body.slots:
        if slot.close_time <= slot.open_time:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Horário de fechamento deve ser maior que o de abertura.",
            )
        key = (slot.weekday, slot.open_time)
        if key in seen:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Faixas de horário duplicadas no mesmo dia.",
            )
        seen.add(key)

    await db.execute(delete(BusinessHours).where(BusinessHours.unit_id == unit.id))
    for slot in body.slots:
        db.add(
            BusinessHours(
                unit_id=unit.id,
                weekday=slot.weekday,
                open_time=slot.open_time,
                close_time=slot.close_time,
            )
        )

    await db.flush()
    out = sorted(body.slots, key=lambda s: (s.weekday, s.open_time))
    await db.commit()
    return out
