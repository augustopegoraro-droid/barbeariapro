"""API de mensalidade/assinatura do CLIENTE FINAL.

Catálogo de planos (owner/manager), venda e gestão de assinaturas (admin),
consumo de pacote e expiração (cron interno). Regra de negócio em
``app.services.membership``; aqui só orquestração e (de)serialização.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import require_full_access, require_manager_access
from app.deps import (
    get_bot_db,
    get_current_user,
    get_tenant_db,
    resolve_current_role,
)
from app.services import membership as svc
from models import (
    Client,
    ClientMembership,
    MembershipPlan,
    MembershipPlanItem,
    MembershipStatus,
    Service,
    User,
)

router = APIRouter(prefix="/memberships", tags=["memberships"])
internal_router = APIRouter(
    prefix="/internal/memberships", tags=["memberships-internal"]
)


# ─── schemas ─────────────────────────────────────────────────────────────────

class PlanItemOut(BaseModel):
    service_id: int
    service_name: Optional[str] = None
    position: int


class PlanOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    price: float
    included_uses: Optional[int]  # None = ilimitado
    duration_days: int
    unlimited_use_value: Optional[float]
    is_active: bool
    items: list[PlanItemOut]


class PlanIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    price: Decimal = Field(..., ge=Decimal("0"))
    included_uses: Optional[int] = Field(None, gt=0, description="None = ilimitado")
    duration_days: int = Field(..., gt=0)
    unlimited_use_value: Optional[Decimal] = Field(None, ge=Decimal("0"))
    service_ids: list[int] = Field(..., min_length=1, description="Serviços do combo (ordenados)")


class PlanUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    price: Optional[Decimal] = Field(None, ge=Decimal("0"))
    included_uses: Optional[int] = Field(None, gt=0)
    duration_days: Optional[int] = Field(None, gt=0)
    unlimited_use_value: Optional[Decimal] = Field(None, ge=Decimal("0"))
    is_active: Optional[bool] = None
    service_ids: Optional[list[int]] = Field(None, min_length=1)
    # Quando included_uses deve passar a ilimitado num PATCH (não dá p/ enviar None).
    set_unlimited: Optional[bool] = Field(None, description="true → torna o plano ilimitado")


class SellIn(BaseModel):
    client_id: int = Field(..., gt=0)
    plan_id: int = Field(..., gt=0)
    start_at: Optional[datetime] = None


class AssignmentIn(BaseModel):
    service_id: int = Field(..., gt=0)
    barber_id: int = Field(..., gt=0)


class ConsumeIn(BaseModel):
    start_at: datetime
    assignments: list[AssignmentIn] = Field(..., min_length=1)


class UsageOut(BaseModel):
    id: int
    appointment_id: int
    recognized_value: float
    used_at: str
    reverted_at: Optional[str]
    created_by_user_id: Optional[int]


class MembershipOut(BaseModel):
    id: int
    public_id: str
    client_id: int
    client_name: Optional[str]
    plan_id: int
    status: str
    start_at: str
    end_at: str
    days_remaining: int
    price_paid: float
    included_uses: Optional[int]  # None = ilimitado
    used_uses: int
    remaining_uses: Optional[int]  # None = ilimitado
    unit_recognized_value: float
    combo: list[PlanItemOut]
    created_at: str
    usages: list[UsageOut]


class ConsumeOut(BaseModel):
    appointment_id: int
    public_id: str
    start_at: str
    end_at: str
    status: str
    total_amount: float
    membership_id: int


class ExpireOut(BaseModel):
    expired: int


# ─── helpers de serialização ─────────────────────────────────────────────────

async def _service_names(db: AsyncSession, service_ids: list[int]) -> dict[int, str]:
    if not service_ids:
        return {}
    rows = (
        await db.execute(
            select(Service.id, Service.name).where(Service.id.in_(service_ids))
        )
    ).all()
    return {r.id: r.name for r in rows}


def _plan_out(plan: MembershipPlan, names: dict[int, str]) -> PlanOut:
    items = [
        PlanItemOut(
            service_id=i.service_id,
            service_name=names.get(i.service_id),
            position=i.position,
        )
        for i in sorted(plan.items, key=lambda x: x.position)
    ]
    return PlanOut(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        price=float(plan.price),
        included_uses=plan.included_uses,
        duration_days=plan.duration_days,
        unlimited_use_value=(
            float(plan.unlimited_use_value)
            if plan.unlimited_use_value is not None
            else None
        ),
        is_active=plan.is_active,
        items=items,
    )


def _membership_out(
    m: ClientMembership, names: dict[int, str], client_name: Optional[str]
) -> MembershipOut:
    now = datetime.now(timezone.utc)
    days_remaining = max(0, (m.end_at - now).days)
    combo = [
        PlanItemOut(
            service_id=c["service_id"],
            service_name=names.get(c["service_id"]),
            position=c["position"],
        )
        for c in sorted(m.combo_snapshot, key=lambda c: c["position"])
    ]
    usages = [
        UsageOut(
            id=u.id,
            appointment_id=u.appointment_id,
            recognized_value=float(u.recognized_value),
            used_at=u.used_at.isoformat(),
            reverted_at=u.reverted_at.isoformat() if u.reverted_at else None,
            created_by_user_id=u.created_by_user_id,
        )
        for u in sorted(m.usages, key=lambda u: u.used_at)
    ]
    return MembershipOut(
        id=m.id,
        public_id=str(m.public_id),
        client_id=m.client_id,
        client_name=client_name,
        plan_id=m.plan_id,
        status=m.status.value,
        start_at=m.start_at.isoformat(),
        end_at=m.end_at.isoformat(),
        days_remaining=days_remaining,
        price_paid=float(m.price_paid),
        included_uses=m.included_uses,
        used_uses=m.used_uses,
        remaining_uses=svc.remaining_uses(m),
        unit_recognized_value=float(m.unit_recognized_value),
        combo=combo,
        created_at=m.created_at.isoformat(),
        usages=usages,
    )


async def _load_membership(db: AsyncSession, membership_id: int) -> ClientMembership:
    m = (
        await db.execute(
            select(ClientMembership)
            .where(ClientMembership.id == membership_id)
            .options(selectinload(ClientMembership.usages))
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Assinatura não encontrada.")
    return m


async def _membership_out_full(db: AsyncSession, m: ClientMembership) -> MembershipOut:
    service_ids = [c["service_id"] for c in m.combo_snapshot]
    names = await _service_names(db, service_ids)
    client = (
        await db.execute(select(Client.name).where(Client.id == m.client_id))
    ).scalar_one_or_none()
    return _membership_out(m, names, client)


# ─── catálogo de planos (owner/manager) ──────────────────────────────────────

@router.get("/planos", response_model=list[PlanOut])
async def listar_planos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    include_inactive: bool = Query(False),
) -> list[PlanOut]:
    require_manager_access(await resolve_current_role(db, current_user))

    stmt = (
        select(MembershipPlan)
        .where(MembershipPlan.deleted_at.is_(None))
        .options(selectinload(MembershipPlan.items))
        .order_by(MembershipPlan.name)
    )
    if not include_inactive:
        stmt = stmt.where(MembershipPlan.is_active.is_(True))
    plans = (await db.execute(stmt)).scalars().all()

    all_ids = sorted({i.service_id for p in plans for i in p.items})
    names = await _service_names(db, all_ids)
    return [_plan_out(p, names) for p in plans]


async def _validate_combo_services(
    db: AsyncSession, service_ids: list[int]
) -> None:
    if len(set(service_ids)) != len(service_ids):
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Serviço repetido no combo.",
        )
    found = (
        await db.execute(
            select(Service.id)
            .where(Service.id.in_(service_ids))
            .where(Service.deleted_at.is_(None))
        )
    ).scalars().all()
    if set(found) != set(service_ids):
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Combo referencia serviço inexistente nesta organização.",
        )


@router.post("/planos", response_model=PlanOut, status_code=http_status.HTTP_201_CREATED)
async def criar_plano(
    body: PlanIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PlanOut:
    require_manager_access(await resolve_current_role(db, current_user))

    if body.included_uses is None and body.unlimited_use_value is None:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Plano ilimitado (included_uses ausente) exige unlimited_use_value.",
        )
    await _validate_combo_services(db, body.service_ids)

    plan = MembershipPlan(
        organization_id=current_user.organization_id,
        name=body.name,
        description=body.description,
        price=body.price,
        included_uses=body.included_uses,
        duration_days=body.duration_days,
        unlimited_use_value=body.unlimited_use_value,
    )
    db.add(plan)
    await db.flush()
    for pos, sid in enumerate(body.service_ids, start=1):
        db.add(
            MembershipPlanItem(
                organization_id=current_user.organization_id,
                plan_id=plan.id,
                service_id=sid,
                position=pos,
            )
        )
    await db.flush()
    await db.refresh(plan, ["items"])
    names = await _service_names(db, body.service_ids)
    out = _plan_out(plan, names)
    await db.commit()
    return out


@router.patch("/planos/{plan_id}", response_model=PlanOut)
async def atualizar_plano(
    body: PlanUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    plan_id: int = Path(..., gt=0),
) -> PlanOut:
    require_manager_access(await resolve_current_role(db, current_user))

    plan = (
        await db.execute(
            select(MembershipPlan)
            .where(MembershipPlan.id == plan_id)
            .where(MembershipPlan.deleted_at.is_(None))
            .options(selectinload(MembershipPlan.items))
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Plano não encontrado.")

    if body.name is not None:
        plan.name = body.name
    if body.description is not None:
        plan.description = body.description
    if body.price is not None:
        plan.price = body.price
    if body.duration_days is not None:
        plan.duration_days = body.duration_days
    if body.is_active is not None:
        plan.is_active = body.is_active
    if body.set_unlimited:
        plan.included_uses = None
    elif body.included_uses is not None:
        plan.included_uses = body.included_uses
    if body.unlimited_use_value is not None:
        plan.unlimited_use_value = body.unlimited_use_value

    # Consistência: ilimitado precisa de unlimited_use_value.
    if plan.included_uses is None and plan.unlimited_use_value is None:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Plano ilimitado exige unlimited_use_value.",
        )

    if body.service_ids is not None:
        await _validate_combo_services(db, body.service_ids)
        for item in list(plan.items):
            await db.delete(item)
        await db.flush()
        for pos, sid in enumerate(body.service_ids, start=1):
            db.add(
                MembershipPlanItem(
                    organization_id=current_user.organization_id,
                    plan_id=plan.id,
                    service_id=sid,
                    position=pos,
                )
            )

    await db.flush()
    await db.refresh(plan, ["items"])
    names = await _service_names(db, [i.service_id for i in plan.items])
    out = _plan_out(plan, names)
    await db.commit()
    return out


@router.delete("/planos/{plan_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def arquivar_plano(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    plan_id: int = Path(..., gt=0),
) -> None:
    require_manager_access(await resolve_current_role(db, current_user))

    plan = (
        await db.execute(
            select(MembershipPlan)
            .where(MembershipPlan.id == plan_id)
            .where(MembershipPlan.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Plano não encontrado.")
    plan.deleted_at = datetime.now(timezone.utc)
    plan.is_active = False
    await db.commit()


# ─── venda / gestão de assinaturas (admin) ───────────────────────────────────

@router.post("", response_model=MembershipOut, status_code=http_status.HTTP_201_CREATED)
async def vender_assinatura(
    body: SellIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MembershipOut:
    require_full_access(await resolve_current_role(db, current_user))

    membership = await svc.sell_membership(
        db,
        organization_id=current_user.organization_id,
        client_id=body.client_id,
        plan_id=body.plan_id,
        sold_by_user_id=current_user.id,
        start_at=body.start_at,
    )
    await db.refresh(membership, ["usages"])
    out = await _membership_out_full(db, membership)
    await db.commit()
    return out


@router.get("/clientes/{client_id}", response_model=dict)
async def assinaturas_do_cliente(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    client_id: int = Path(..., gt=0),
) -> dict:
    require_full_access(await resolve_current_role(db, current_user))

    client = (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if not client:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    memberships = (
        await db.execute(
            select(ClientMembership)
            .where(ClientMembership.client_id == client_id)
            .options(selectinload(ClientMembership.usages))
            .order_by(ClientMembership.created_at.desc())
        )
    ).scalars().all()

    all_service_ids = sorted(
        {c["service_id"] for m in memberships for c in m.combo_snapshot}
    )
    names = await _service_names(db, all_service_ids)

    now = datetime.now(timezone.utc)
    active = next(
        (
            m
            for m in memberships
            if m.status == MembershipStatus.ativa and m.end_at > now
        ),
        None,
    )
    out_all = [_membership_out(m, names, client.name) for m in memberships]
    return {
        "client_id": client_id,
        "client_name": client.name,
        "active": _membership_out(active, names, client.name) if active else None,
        "memberships": [o.model_dump() for o in out_all],
    }


@router.get("/{membership_id}", response_model=MembershipOut)
async def detalhe_assinatura(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    membership_id: int = Path(..., gt=0),
) -> MembershipOut:
    require_full_access(await resolve_current_role(db, current_user))
    m = await _load_membership(db, membership_id)
    return await _membership_out_full(db, m)


@router.post("/{membership_id}/cancelar", response_model=MembershipOut)
async def cancelar_assinatura(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    membership_id: int = Path(..., gt=0),
) -> MembershipOut:
    require_full_access(await resolve_current_role(db, current_user))
    m = await _load_membership(db, membership_id)
    if m.status == MembershipStatus.cancelada:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Assinatura já cancelada.")
    m.status = MembershipStatus.cancelada
    m.canceled_at = datetime.now(timezone.utc)
    await db.flush()
    out = await _membership_out_full(db, m)
    await db.commit()
    return out


@router.post(
    "/{membership_id}/renovar",
    response_model=MembershipOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def renovar_assinatura(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    membership_id: int = Path(..., gt=0),
) -> MembershipOut:
    """Cria uma nova assinatura a partir do mesmo plano (renovação manual).

    Preparado para renovação automática: um cron pode chamar a mesma função.
    """
    require_full_access(await resolve_current_role(db, current_user))
    old = await _load_membership(db, membership_id)
    new = await svc.sell_membership(
        db,
        organization_id=current_user.organization_id,
        client_id=old.client_id,
        plan_id=old.plan_id,
        sold_by_user_id=current_user.id,
        start_at=None,
    )
    await db.refresh(new, ["usages"])
    out = await _membership_out_full(db, new)
    await db.commit()
    return out


@router.post(
    "/{membership_id}/usos",
    response_model=ConsumeOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def consumir_pacote(
    body: ConsumeIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    membership_id: int = Path(..., gt=0),
) -> ConsumeOut:
    require_full_access(await resolve_current_role(db, current_user))

    appt = await svc.consume_membership(
        db,
        organization_id=current_user.organization_id,
        membership_id=membership_id,
        start_at=body.start_at,
        assignments=[a.model_dump() for a in body.assignments],
        created_by_user_id=current_user.id,
    )
    out = ConsumeOut(
        appointment_id=appt.id,
        public_id=str(appt.public_id),
        start_at=appt.start_at.isoformat(),
        end_at=appt.end_at.isoformat(),
        status=appt.status.value,
        total_amount=float(appt.total_amount),
        membership_id=membership_id,
    )
    await db.commit()
    return out


# ─── expiração (cron interno via X-Bot-Token) ────────────────────────────────

@internal_router.post("/expirar", response_model=ExpireOut)
async def expirar_assinaturas(
    db: Annotated[AsyncSession, Depends(get_bot_db)],
) -> ExpireOut:
    """Marca como 'vencida' as assinaturas cuja vigência terminou (cron n8n)."""
    result = await svc.expire_memberships(db)
    return ExpireOut(**result)
