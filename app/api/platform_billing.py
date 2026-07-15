# file: app/api/platform_billing.py
"""Billing no painel de PLATAFORMA (superadmin M8).

Gestão de planos (CRUD + espelho no gateway), assinaturas cross-org com
dunning, ações administrativas (cancelar/pausar/retomar/trocar plano/dias
grátis/cupom/crédito), cupons e reprocesso de webhooks.

Mesmo modelo de acesso do platform.py: guard `require_platform_admin`;
catálogos globais (plans/plan_prices/plan_limits/coupons/webhook_events, sem
RLS) leem/escrevem direto na sessão do request; dados por-org (RLS) via função
SECURITY DEFINER ou pelas sessões helper do serviço de billing.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.platform import PlatformAdminId, PlatformDB
from app.services import platform as platform_svc
from app.services.billing import get_billing_provider
from app.services.billing import service as billing_svc
from app.services.billing.provider import BillingProviderError
from models import Coupon, Plan, PlanLimit, PlanPrice, WebhookEvent

router = APIRouter(prefix="/platform/billing", tags=["platform-billing"])


def _actor(admin_id: int) -> dict:
    return {"type": "platform_admin", "id": admin_id, "label": f"superadmin#{admin_id}"}


def _svc_call_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, billing_svc.BillingServiceError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    if isinstance(exc, BillingProviderError):
        return HTTPException(status_code=502, detail=f"Gateway indisponível: {exc}")
    raise exc


# ─── planos ─────────────────────────────────────────────────────────────────

class PlanPriceOut(BaseModel):
    cycle: str
    amount: float
    currency: str
    provider_price_id: Optional[str] = None
    active: bool


class PlanFullOut(BaseModel):
    id: int
    slug: Optional[str] = None
    name: str
    description: Optional[str] = None
    price_month: float
    is_active: bool
    sort_order: int
    stripe_product_id: Optional[str] = None
    prices: list[PlanPriceOut]
    limits: dict[str, Optional[int]]


class PlanCreateIn(BaseModel):
    name: str = Field(..., min_length=1)
    slug: Optional[str] = None
    description: Optional[str] = None
    price_month: float = Field(..., ge=0)
    price_year: Optional[float] = Field(None, ge=0)
    limits: dict[str, Optional[int]] = Field(default_factory=dict)
    sort_order: int = 0


class PlanPatchIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    price_month: Optional[float] = Field(None, ge=0)
    price_year: Optional[float] = Field(None, ge=0)
    limits: Optional[dict[str, Optional[int]]] = None


async def _plan_full(db, plan: Plan) -> PlanFullOut:
    prices = (
        await db.execute(select(PlanPrice).where(PlanPrice.plan_id == plan.id))
    ).scalars().all()
    limits = (
        await db.execute(select(PlanLimit).where(PlanLimit.plan_id == plan.id))
    ).scalars().all()
    limit_map: dict[str, Optional[int]] = {l.limit_key: l.value for l in limits}
    limit_map.setdefault("units", plan.max_units)
    limit_map.setdefault("barbers", plan.max_barbers)
    return PlanFullOut(
        id=plan.id, slug=plan.slug, name=plan.name, description=plan.description,
        price_month=float(plan.price_month), is_active=plan.is_active,
        sort_order=plan.sort_order, stripe_product_id=plan.stripe_product_id,
        prices=[
            PlanPriceOut(
                cycle=p.cycle, amount=float(p.amount), currency=p.currency,
                provider_price_id=p.provider_price_id, active=p.active,
            )
            for p in prices
        ],
        limits=limit_map,
    )


@router.get("/plans", response_model=list[PlanFullOut])
async def list_plans(_admin: PlatformAdminId, db: PlatformDB) -> list[PlanFullOut]:
    plans = (
        await db.execute(select(Plan).order_by(Plan.sort_order, Plan.id))
    ).scalars().all()
    return [await _plan_full(db, p) for p in plans]


async def _upsert_price(db, plan: Plan, cycle: str, amount: float) -> None:
    price = (
        await db.execute(
            select(PlanPrice).where(PlanPrice.plan_id == plan.id, PlanPrice.cycle == cycle)
        )
    ).scalars().first()
    if price is None:
        db.add(PlanPrice(plan_id=plan.id, cycle=cycle, amount=Decimal(str(amount))))
    elif float(price.amount) != amount:
        price.amount = Decimal(str(amount))
        # Preço mudou → o Price antigo do gateway não vale mais; o próximo
        # sync cria um novo (Prices são imutáveis na Stripe).
        price.provider_price_id = None
    if cycle == "monthly":
        plan.price_month = Decimal(str(amount))


async def _upsert_limits(db, plan: Plan, limits: dict[str, Optional[int]]) -> None:
    for key, value in limits.items():
        row = (
            await db.execute(
                select(PlanLimit).where(PlanLimit.plan_id == plan.id, PlanLimit.limit_key == key)
            )
        ).scalars().first()
        if row is None:
            db.add(PlanLimit(plan_id=plan.id, limit_key=key, value=value))
        else:
            row.value = value
        # Retrocompat: espelha nos campos legados usados pelo app do tenant.
        if key == "units" and value is not None:
            plan.max_units = value
        if key == "barbers" and value is not None:
            plan.max_barbers = value


@router.post("/plans", response_model=PlanFullOut, status_code=status.HTTP_201_CREATED)
async def create_plan(body: PlanCreateIn, _admin: PlatformAdminId, db: PlatformDB) -> PlanFullOut:
    slug = body.slug or "-".join(body.name.lower().split())
    plan = Plan(
        name=body.name, slug=slug, description=body.description,
        price_month=Decimal(str(body.price_month)),
        max_units=body.limits.get("units") or 1,
        max_barbers=body.limits.get("barbers") or 1,
        sort_order=body.sort_order,
    )
    db.add(plan)
    await db.flush()
    await _upsert_price(db, plan, "monthly", body.price_month)
    if body.price_year is not None:
        await _upsert_price(db, plan, "yearly", body.price_year)
    await _upsert_limits(db, plan, body.limits)
    await db.flush()  # sessão tem autoflush=False — materializa antes de reler
    return await _plan_full(db, plan)


@router.patch("/plans/{plan_id}", response_model=PlanFullOut)
async def patch_plan(plan_id: int, body: PlanPatchIn, _admin: PlatformAdminId,
                     db: PlatformDB) -> PlanFullOut:
    plan = (
        await db.execute(select(Plan).where(Plan.id == plan_id))
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plano não encontrado.")
    if body.name is not None:
        plan.name = body.name
    if body.description is not None:
        plan.description = body.description
    if body.is_active is not None:
        plan.is_active = body.is_active
    if body.sort_order is not None:
        plan.sort_order = body.sort_order
    if body.price_month is not None:
        await _upsert_price(db, plan, "monthly", body.price_month)
    if body.price_year is not None:
        await _upsert_price(db, plan, "yearly", body.price_year)
    if body.limits:
        await _upsert_limits(db, plan, body.limits)
    await db.flush()  # sessão tem autoflush=False — materializa antes de reler
    return await _plan_full(db, plan)


@router.post("/plans/{plan_id}/sync", response_model=PlanFullOut)
async def sync_plan(plan_id: int, _admin: PlatformAdminId, db: PlatformDB) -> PlanFullOut:
    """Espelha Product/Prices no gateway ativo e persiste os ids externos."""
    plan = (
        await db.execute(select(Plan).where(Plan.id == plan_id))
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plano não encontrado.")
    prices = (
        await db.execute(
            select(PlanPrice).where(PlanPrice.plan_id == plan.id, PlanPrice.active.is_(True))
        )
    ).scalars().all()
    provider = get_billing_provider()
    try:
        product_id, price_ids = await provider.sync_plan(
            plan_slug=plan.slug or f"plan-{plan.id}",
            plan_name=plan.name,
            product_id=plan.stripe_product_id if provider.name == "stripe" else None,
            prices=[
                {"cycle": p.cycle, "amount": p.amount, "currency": p.currency,
                 "provider_price_id": p.provider_price_id}
                for p in prices
            ],
        )
    except BillingProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Gateway indisponível: {exc}")
    if provider.name == "stripe":
        plan.stripe_product_id = product_id
    for p in prices:
        if p.cycle in price_ids:
            p.provider_price_id = price_ids[p.cycle]
    return await _plan_full(db, plan)


# ─── assinaturas (cross-org + ações) ────────────────────────────────────────

class BillingSubscriptionRowOut(BaseModel):
    org_id: int
    org_name: str
    suspended: bool
    sub_id: int
    status: str
    provider: str
    cancel_at_period_end: bool
    current_period_end: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    plan_price_month: Optional[float] = None
    open_invoices: int
    open_amount: float
    days_overdue: int
    last_attempt: Optional[int] = None
    last_attempt_error: Optional[str] = None
    next_retry_at: Optional[datetime] = None


@router.get("/subscriptions", response_model=list[BillingSubscriptionRowOut])
async def list_subscriptions(_admin: PlatformAdminId, db: PlatformDB) -> list[BillingSubscriptionRowOut]:
    rows = await platform_svc.billing_subscriptions(db)
    return [
        BillingSubscriptionRowOut(
            org_id=r["org_id"], org_name=r["org_name"],
            suspended=r["org_deleted_at"] is not None,
            sub_id=r["sub_id"], status=r["status"], provider=r["provider"],
            cancel_at_period_end=r["cancel_at_period_end"],
            current_period_end=r["current_period_end"], trial_end=r["trial_end"],
            plan_id=r["plan_id"], plan_name=r["plan_name"],
            plan_price_month=float(r["plan_price_month"]) if r["plan_price_month"] is not None else None,
            open_invoices=r["open_invoices"], open_amount=float(r["open_amount"] or 0),
            days_overdue=r["days_overdue"] or 0,
            last_attempt=r["last_attempt"], last_attempt_error=r["last_attempt_error"],
            next_retry_at=r["next_retry_at"],
        )
        for r in rows
    ]


class CancelIn(BaseModel):
    at_period_end: bool = True


class ChangePlanIn(BaseModel):
    plan_id: int = Field(..., gt=0)
    cycle: str = Field("monthly", pattern="^(monthly|yearly)$")


class GrantDaysIn(BaseModel):
    days: int = Field(..., gt=0, le=365)


class ApplyCouponIn(BaseModel):
    code: str = Field(..., min_length=1)
    reason: Optional[str] = None


class GrantCreditIn(BaseModel):
    amount: float = Field(..., description="Positivo concede; negativo consome.")
    reason: Optional[str] = None


class ActionOut(BaseModel):
    ok: bool = True


async def _run(
    coro, *, db, admin_id: int, org_id: int, action: str, category: str,
    reason: Optional[str] = None, metadata: Optional[dict] = None,
) -> ActionOut:
    """Executa a ação de billing e registra a auditoria da plataforma (M9)."""
    try:
        await coro
    except (billing_svc.BillingServiceError, BillingProviderError) as exc:
        raise _svc_call_errors(exc)
    await platform_svc.audit_add(
        db, admin_id, action=action, category=category,
        target_type="subscription", org_id=org_id,
        reason=reason, metadata=metadata,
    )
    return ActionOut()


@router.post("/orgs/{org_id}/cancel", response_model=ActionOut)
async def cancel(org_id: int, body: CancelIn, admin_id: PlatformAdminId, db: PlatformDB) -> ActionOut:
    return await _run(
        billing_svc.cancel_subscription(org_id, at_period_end=body.at_period_end, actor=_actor(admin_id)),
        db=db, admin_id=admin_id, org_id=org_id,
        action="subscription_canceled", category="subscription",
        metadata={"at_period_end": body.at_period_end},
    )


@router.post("/orgs/{org_id}/reactivate", response_model=ActionOut)
async def reactivate(org_id: int, admin_id: PlatformAdminId, db: PlatformDB) -> ActionOut:
    return await _run(
        billing_svc.reactivate_subscription(org_id, actor=_actor(admin_id)),
        db=db, admin_id=admin_id, org_id=org_id,
        action="subscription_reactivated", category="subscription",
    )


@router.post("/orgs/{org_id}/pause", response_model=ActionOut)
async def pause(org_id: int, admin_id: PlatformAdminId, db: PlatformDB) -> ActionOut:
    return await _run(
        billing_svc.pause_subscription(org_id, actor=_actor(admin_id)),
        db=db, admin_id=admin_id, org_id=org_id,
        action="subscription_paused", category="subscription",
    )


@router.post("/orgs/{org_id}/resume", response_model=ActionOut)
async def resume(org_id: int, admin_id: PlatformAdminId, db: PlatformDB) -> ActionOut:
    return await _run(
        billing_svc.resume_subscription(org_id, actor=_actor(admin_id)),
        db=db, admin_id=admin_id, org_id=org_id,
        action="subscription_resumed", category="subscription",
    )


@router.post("/orgs/{org_id}/change-plan", response_model=ActionOut)
async def change_plan(org_id: int, body: ChangePlanIn, admin_id: PlatformAdminId, db: PlatformDB) -> ActionOut:
    return await _run(
        billing_svc.change_plan(org_id, body.plan_id, cycle=body.cycle, actor=_actor(admin_id)),
        db=db, admin_id=admin_id, org_id=org_id,
        action="plan_changed", category="subscription",
        metadata={"plan_id": body.plan_id, "cycle": body.cycle},
    )


@router.post("/orgs/{org_id}/grant-days", response_model=ActionOut)
async def grant_days(org_id: int, body: GrantDaysIn, admin_id: PlatformAdminId, db: PlatformDB) -> ActionOut:
    return await _run(
        billing_svc.grant_free_days(org_id, body.days, actor=_actor(admin_id)),
        db=db, admin_id=admin_id, org_id=org_id,
        action="free_days_granted", category="financial",
        metadata={"days": body.days},
    )


@router.post("/orgs/{org_id}/apply-coupon", response_model=ActionOut)
async def apply_coupon(org_id: int, body: ApplyCouponIn, admin_id: PlatformAdminId, db: PlatformDB) -> ActionOut:
    return await _run(
        billing_svc.apply_coupon(org_id, body.code, reason=body.reason, actor=_actor(admin_id)),
        db=db, admin_id=admin_id, org_id=org_id,
        action="coupon_applied", category="financial",
        reason=body.reason, metadata={"code": body.code},
    )


@router.post("/orgs/{org_id}/credits", response_model=ActionOut)
async def grant_credit(org_id: int, body: GrantCreditIn, admin_id: PlatformAdminId, db: PlatformDB) -> ActionOut:
    return await _run(
        billing_svc.grant_credit(org_id, Decimal(str(body.amount)), reason=body.reason, actor=_actor(admin_id)),
        db=db, admin_id=admin_id, org_id=org_id,
        action="credit_granted", category="financial",
        reason=body.reason, metadata={"amount": body.amount},
    )


# ─── cupons ─────────────────────────────────────────────────────────────────

class CouponOut(BaseModel):
    id: int
    code: str
    percent_off: Optional[float] = None
    amount_off: Optional[float] = None
    duration: str
    duration_months: Optional[int] = None
    max_redemptions: Optional[int] = None
    times_redeemed: int
    valid_until: Optional[datetime] = None
    active: bool


class CouponCreateIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=40)
    percent_off: Optional[float] = Field(None, gt=0, le=100)
    amount_off: Optional[float] = Field(None, gt=0)
    duration: str = Field("once", pattern="^(once|repeating|forever)$")
    duration_months: Optional[int] = Field(None, gt=0)
    max_redemptions: Optional[int] = Field(None, gt=0)
    valid_until: Optional[datetime] = None


def _coupon_out(c: Coupon) -> CouponOut:
    return CouponOut(
        id=c.id, code=c.code,
        percent_off=float(c.percent_off) if c.percent_off is not None else None,
        amount_off=float(c.amount_off) if c.amount_off is not None else None,
        duration=c.duration, duration_months=c.duration_months,
        max_redemptions=c.max_redemptions, times_redeemed=c.times_redeemed,
        valid_until=c.valid_until, active=c.active,
    )


@router.get("/coupons", response_model=list[CouponOut])
async def list_coupons(_admin: PlatformAdminId, db: PlatformDB) -> list[CouponOut]:
    rows = (await db.execute(select(Coupon).order_by(Coupon.id.desc()))).scalars().all()
    return [_coupon_out(c) for c in rows]


@router.post("/coupons", response_model=CouponOut, status_code=status.HTTP_201_CREATED)
async def create_coupon(body: CouponCreateIn, _admin: PlatformAdminId, db: PlatformDB) -> CouponOut:
    if (body.percent_off is None) == (body.amount_off is None):
        raise HTTPException(status_code=400, detail="Informe percent_off OU amount_off.")
    if body.duration == "repeating" and not body.duration_months:
        raise HTTPException(status_code=400, detail="duration_months é obrigatório para 'repeating'.")
    coupon = Coupon(
        code=body.code.strip().upper(),
        percent_off=Decimal(str(body.percent_off)) if body.percent_off is not None else None,
        amount_off=Decimal(str(body.amount_off)) if body.amount_off is not None else None,
        duration=body.duration, duration_months=body.duration_months,
        max_redemptions=body.max_redemptions, valid_until=body.valid_until,
    )
    db.add(coupon)
    try:
        await db.flush()
    except IntegrityError:
        # V28: só a violação de UNIQUE vira "já existe" — qualquer outro erro
        # (ex.: permissão, conexão) propaga de verdade em vez de ficar
        # mascarado como um 409 enganoso (achado real desta sessão: um GRANT
        # revogado por engano em `coupons` apareceu como "já existe" até o
        # log do Postgres revelar que era "permission denied").
        await db.rollback()
        raise HTTPException(status_code=409, detail="Código de cupom já existe.")
    return _coupon_out(coupon)


@router.post("/coupons/{coupon_id}/deactivate", response_model=CouponOut)
async def deactivate_coupon(coupon_id: int, _admin: PlatformAdminId, db: PlatformDB) -> CouponOut:
    coupon = (
        await db.execute(select(Coupon).where(Coupon.id == coupon_id))
    ).scalar_one_or_none()
    if coupon is None:
        raise HTTPException(status_code=404, detail="Cupom não encontrado.")
    coupon.active = False
    return _coupon_out(coupon)


# ─── webhooks (auditoria + replay) ──────────────────────────────────────────

class WebhookEventOut(BaseModel):
    id: int
    provider: str
    event_id: str
    event_type: str
    organization_id: Optional[int] = None
    status: str
    error: Optional[str] = None
    attempts: int
    received_at: datetime
    processed_at: Optional[datetime] = None


@router.get("/webhook-events", response_model=list[WebhookEventOut])
async def list_webhook_events(
    _admin: PlatformAdminId, db: PlatformDB, event_status: Optional[str] = None
) -> list[WebhookEventOut]:
    stmt = select(WebhookEvent).order_by(WebhookEvent.id.desc()).limit(100)
    if event_status:
        stmt = stmt.where(WebhookEvent.status == event_status)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        WebhookEventOut(
            id=w.id, provider=w.provider, event_id=w.event_id, event_type=w.event_type,
            organization_id=w.organization_id, status=w.status, error=w.error,
            attempts=w.attempts, received_at=w.received_at, processed_at=w.processed_at,
        )
        for w in rows
    ]


@router.post("/webhook-events/{webhook_event_id}/reprocess")
async def reprocess_webhook(webhook_event_id: int, _admin: PlatformAdminId) -> dict:
    try:
        return await billing_svc.reprocess_webhook_event(webhook_event_id)
    except (billing_svc.BillingServiceError, BillingProviderError) as exc:
        raise _svc_call_errors(exc)
