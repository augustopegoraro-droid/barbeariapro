"""Endpoints do módulo de fidelidade.

Fase 1 (legado, mantido p/ compat): snapshot nivel/categoria + reativação.
Fase 2 (points-driven): saldo de pontos, tier derivado, extrato (ledger),
resgate (voucher), ajuste manual e configuração de regra por org.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.core.rbac import require_full_access, require_manager_access
from app.deps import (
    get_bot_db,
    get_bot_org_id,
    get_current_user,
    get_tenant_db,
    resolve_current_role,
)
from app.services import loyalty as loyalty_svc
from app.services import reactivation as reactivation_svc
from models import User
from models.loyalty import ClientLoyalty, LoyaltyPointEntry, LoyaltyRule, LoyaltyTier, LoyaltyVoucher

router = APIRouter(prefix="/loyalty", tags=["loyalty"])
internal_router = APIRouter(prefix="/internal/loyalty", tags=["loyalty-internal"])
BotDB = Annotated[AsyncSession, Depends(get_bot_db)]
BotOrgId = Annotated[int, Depends(get_bot_org_id)]
TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoyaltyOut(BaseModel):
    client_id: int
    visit_count: int
    total_spent: float
    last_visit_at: Optional[str]
    nivel: str
    status: str
    categoria: Optional[str]
    preferred_barber_id: Optional[int]
    preferred_service_id: Optional[int]
    benefit: str
    next_milestone_categoria: str
    next_milestone_nivel: str
    # Fase 2 (points-driven) — aditivo
    points_balance: int
    tier_name: Optional[str]
    tier_discount_pct: Optional[float]
    tier_perks: list[str]
    next_tier: Optional[str]
    points_to_next: int


class LedgerEntryOut(BaseModel):
    id: int
    type: str
    points_delta: int
    balance_after: int
    reason: str
    ref_appointment_id: Optional[int]
    ref_voucher_id: Optional[int]
    created_at: str


class VoucherOut(BaseModel):
    id: int
    amount_brl: float
    points_spent: int
    status: str
    created_at: str
    consumed_at: Optional[str]


class TierOut(BaseModel):
    id: int
    name: str
    min_points: int
    discount_pct: float
    perks: list[str]
    sort_order: int
    is_active: bool


class RuleOut(BaseModel):
    points_per_brl: float
    points_per_visit: int
    redemption_brl_per_point: float
    expiration_days: Optional[int]


class RuleIn(BaseModel):
    points_per_brl: float = Field(ge=0)
    points_per_visit: int = Field(ge=0)
    redemption_brl_per_point: float = Field(ge=0)
    expiration_days: Optional[int] = Field(default=None, ge=0)


class AdjustIn(BaseModel):
    delta: int
    reason: str = ""


class RedeemIn(BaseModel):
    points: int = Field(gt=0)


class BalanceOut(BaseModel):
    client_id: int
    points_balance: int
    tier_name: Optional[str]


class ReactivationOut(BaseModel):
    sent: int
    skipped: int
    total_targets: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _tiers_for(org_id: int, db: AsyncSession) -> list[LoyaltyTier]:
    return list(
        (
            await db.execute(
                select(LoyaltyTier)
                .where(LoyaltyTier.organization_id == org_id)
                .where(LoyaltyTier.is_active.is_(True))
                .order_by(LoyaltyTier.min_points)
            )
        ).scalars()
    )


def _tier_out(t: LoyaltyTier) -> TierOut:
    return TierOut(
        id=t.id, name=t.name, min_points=t.min_points, discount_pct=float(t.discount_pct),
        perks=list(t.perks or []), sort_order=t.sort_order, is_active=t.is_active,
    )


# ---------------------------------------------------------------------------
# Consulta (bot)
# ---------------------------------------------------------------------------


@router.get("/clients/{client_id}", response_model=LoyaltyOut)
async def get_client_loyalty(client_id: int, db: BotDB, org_id: BotOrgId) -> LoyaltyOut:
    loyalty = (
        await db.execute(select(ClientLoyalty).where(ClientLoyalty.client_id == client_id))
    ).scalar_one_or_none()
    if not loyalty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dados de fidelidade não encontrados para este cliente.",
        )

    milestone = loyalty_svc.next_milestone(loyalty.visit_count, loyalty.total_spent)

    tiers = await _tiers_for(org_id, db)
    tier = loyalty_svc.tier_for_points(loyalty.points_balance, tiers)
    nxt = loyalty_svc.points_to_next_tier(loyalty.points_balance, tiers)

    return LoyaltyOut(
        client_id=loyalty.client_id,
        visit_count=loyalty.visit_count,
        total_spent=float(loyalty.total_spent),
        last_visit_at=loyalty.last_visit_at.isoformat() if loyalty.last_visit_at else None,
        nivel=loyalty.nivel.value,
        status=loyalty.status.value,
        categoria=loyalty.categoria.value if loyalty.categoria else None,
        preferred_barber_id=loyalty.preferred_barber_id,
        preferred_service_id=loyalty.preferred_service_id,
        benefit=loyalty_svc.resolve_benefit(loyalty.nivel, loyalty.categoria),
        next_milestone_categoria=milestone["categoria"],
        next_milestone_nivel=milestone["nivel"],
        points_balance=loyalty.points_balance,
        tier_name=tier.name if tier else None,
        tier_discount_pct=float(tier.discount_pct) if tier else None,
        tier_perks=list(tier.perks or []) if tier else [],
        next_tier=nxt["next_tier"],  # type: ignore[arg-type]
        points_to_next=int(nxt["points_needed"]),
    )


# ---------------------------------------------------------------------------
# Pontos: extrato / ajuste / resgate / vouchers (painel)
# ---------------------------------------------------------------------------


@router.get("/clients/{client_id}/ledger", response_model=list[LedgerEntryOut])
async def get_ledger(client_id: int, current_user: CurrentUser, db: TenantDB) -> list[LedgerEntryOut]:
    await require_permission(db, current_user, "loyalty.view")
    rows = (
        await db.execute(
            select(LoyaltyPointEntry)
            .where(LoyaltyPointEntry.client_id == client_id)
            .order_by(LoyaltyPointEntry.created_at.desc(), LoyaltyPointEntry.id.desc())
            .limit(200)
        )
    ).scalars().all()
    return [
        LedgerEntryOut(
            id=e.id, type=e.type.value, points_delta=e.points_delta, balance_after=e.balance_after,
            reason=e.reason, ref_appointment_id=e.ref_appointment_id, ref_voucher_id=e.ref_voucher_id,
            created_at=e.created_at.isoformat(),
        )
        for e in rows
    ]


@router.post("/clients/{client_id}/points", response_model=BalanceOut)
async def adjust_points(
    client_id: int, body: AdjustIn, current_user: CurrentUser, db: TenantDB
) -> BalanceOut:
    await require_permission(db, current_user, "loyalty.manage")
    org_id = current_user.organization_id
    try:
        await loyalty_svc.adjust_points(
            org_id, client_id, body.delta, body.reason, db, by_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    loyalty = (
        await db.execute(select(ClientLoyalty).where(ClientLoyalty.client_id == client_id))
    ).scalar_one()
    tiers = await _tiers_for(org_id, db)
    tier = loyalty_svc.tier_for_points(loyalty.points_balance, tiers)
    return BalanceOut(
        client_id=client_id, points_balance=loyalty.points_balance,
        tier_name=tier.name if tier else None,
    )


@router.post("/clients/{client_id}/redeem", response_model=VoucherOut)
async def redeem(client_id: int, body: RedeemIn, current_user: CurrentUser, db: TenantDB) -> VoucherOut:
    await require_permission(db, current_user, "loyalty.view")
    try:
        voucher = await loyalty_svc.redeem_points(
            current_user.organization_id, client_id, body.points, db, by_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return VoucherOut(
        id=voucher.id, amount_brl=float(voucher.amount_brl), points_spent=voucher.points_spent,
        status=voucher.status.value, created_at=voucher.created_at.isoformat(), consumed_at=None,
    )


@router.get("/clients/{client_id}/vouchers", response_model=list[VoucherOut])
async def get_vouchers(client_id: int, current_user: CurrentUser, db: TenantDB) -> list[VoucherOut]:
    await require_permission(db, current_user, "loyalty.view")
    rows = (
        await db.execute(
            select(LoyaltyVoucher)
            .where(LoyaltyVoucher.client_id == client_id)
            .order_by(LoyaltyVoucher.created_at.desc())
        )
    ).scalars().all()
    return [
        VoucherOut(
            id=v.id, amount_brl=float(v.amount_brl), points_spent=v.points_spent,
            status=v.status.value, created_at=v.created_at.isoformat(),
            consumed_at=v.consumed_at.isoformat() if v.consumed_at else None,
        )
        for v in rows
    ]


# ---------------------------------------------------------------------------
# Configuração (tiers / regra) — owner/manager
# ---------------------------------------------------------------------------


@router.get("/tiers", response_model=list[TierOut])
async def get_tiers(current_user: CurrentUser, db: TenantDB) -> list[TierOut]:
    await require_permission(db, current_user, "loyalty.view")
    tiers = await loyalty_svc.get_or_seed_tiers(current_user.organization_id, db)
    return [_tier_out(t) for t in tiers]


@router.get("/rules", response_model=RuleOut)
async def get_rules(current_user: CurrentUser, db: TenantDB) -> RuleOut:
    await require_permission(db, current_user, "loyalty.view")
    rule = await loyalty_svc.get_or_seed_rule(current_user.organization_id, db)
    return RuleOut(
        points_per_brl=float(rule.points_per_brl), points_per_visit=rule.points_per_visit,
        redemption_brl_per_point=float(rule.redemption_brl_per_point),
        expiration_days=rule.expiration_days,
    )


@router.put("/rules", response_model=RuleOut)
async def put_rules(body: RuleIn, current_user: CurrentUser, db: TenantDB) -> RuleOut:
    await require_permission(db, current_user, "loyalty.manage")
    rule = await loyalty_svc.get_or_seed_rule(current_user.organization_id, db)
    rule.points_per_brl = Decimal(str(body.points_per_brl))
    rule.points_per_visit = body.points_per_visit
    rule.redemption_brl_per_point = Decimal(str(body.redemption_brl_per_point))
    rule.expiration_days = body.expiration_days
    await db.flush()
    return RuleOut(
        points_per_brl=float(rule.points_per_brl), points_per_visit=rule.points_per_visit,
        redemption_brl_per_point=float(rule.redemption_brl_per_point),
        expiration_days=rule.expiration_days,
    )


# ---------------------------------------------------------------------------
# Reativação (cron n8n)
# ---------------------------------------------------------------------------


@internal_router.post("/reactivation/run", response_model=ReactivationOut)
async def run_reactivation(db: BotDB, org_id: BotOrgId) -> ReactivationOut:
    result = await reactivation_svc.run(org_id=org_id, session=db)
    return ReactivationOut(**result)
