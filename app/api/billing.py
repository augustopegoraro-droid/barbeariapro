# file: app/api/billing.py
"""Billing do SaaS — rotas de TENANT, webhook do gateway e cron interno.

- `/billing/*` (tenant, `get_tenant_db` + owner/manager): a barbearia vê a
  própria assinatura, inicia checkout e abre o Customer Portal.
- `/billing/webhooks/{provider}`: SEM auth de sessão — a autenticidade é a
  ASSINATURA criptográfica verificada pelo provider (`parse_webhook`).
- `/internal/billing/run-lifecycle`: cron (n8n) com `X-Bot-Token`
  (tempo-constante via `secrets_match`, molde wa_webhook).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.entitlements import get_entitlements
from app.core.rbac import require_manager_access
from app.core.security import secrets_match
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.services.billing.provider import BillingProviderError
from app.services.billing import service as billing_svc
from models import Invoice, Plan, PlanPrice, Subscription, User

router = APIRouter(prefix="/billing", tags=["billing"])
internal_router = APIRouter(prefix="/internal/billing", tags=["billing-internal"])

TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def _require_manager(db: AsyncSession, user: User) -> None:
    role = await resolve_current_role(db, user)
    require_manager_access(role)


# ─── schemas ────────────────────────────────────────────────────────────────

class PlanPublicOut(BaseModel):
    id: int
    slug: Optional[str] = None
    name: str
    description: Optional[str] = None
    price_month: float
    prices: dict[str, float]  # cycle → valor


class SubscriptionOut(BaseModel):
    status: str
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    price_month: Optional[float] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    provider: str = "manual"
    has_gateway: bool = False  # tem assinatura viva no gateway (portal disponível)
    level: str  # full | restricted | blocked
    limits: dict[str, Optional[int]] = {}
    features: dict[str, bool] = {}


class CheckoutIn(BaseModel):
    plan_id: int = Field(..., gt=0)
    cycle: str = Field("monthly", pattern="^(monthly|yearly)$")
    success_url: str = Field(..., min_length=8)
    cancel_url: str = Field(..., min_length=8)


class PortalIn(BaseModel):
    return_url: str = Field(..., min_length=8)


class UrlOut(BaseModel):
    url: str


class InvoiceOut(BaseModel):
    id: int
    number: Optional[str] = None
    status: str
    amount_due: float
    amount_paid: float
    currency: str
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    due_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    hosted_invoice_url: Optional[str] = None
    pdf_url: Optional[str] = None


# ─── tenant ─────────────────────────────────────────────────────────────────

@router.get("/plans", response_model=list[PlanPublicOut])
async def listar_planos(db: TenantDB, user: CurrentUser) -> list[PlanPublicOut]:
    """Catálogo público de planos ativos (para a tela de upgrade)."""
    plans = (
        await db.execute(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order, Plan.id)
        )
    ).scalars().all()
    prices = (
        await db.execute(select(PlanPrice).where(PlanPrice.active.is_(True)))
    ).scalars().all()
    by_plan: dict[int, dict[str, float]] = {}
    for p in prices:
        by_plan.setdefault(p.plan_id, {})[p.cycle] = float(p.amount)
    return [
        PlanPublicOut(
            id=p.id, slug=p.slug, name=p.name, description=p.description,
            price_month=float(p.price_month), prices=by_plan.get(p.id, {}),
        )
        for p in plans
    ]


@router.get("/subscription", response_model=SubscriptionOut)
async def minha_assinatura(db: TenantDB, user: CurrentUser) -> SubscriptionOut:
    """Assinatura da barbearia logada + entitlements (RLS escopa a org)."""
    sub = (
        await db.execute(
            select(Subscription)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
            .limit(1)
        )
    ).scalars().first()
    ent = await get_entitlements(db)
    if sub is None:
        return SubscriptionOut(status="sem_assinatura", level=ent.level,
                               limits=ent.limits, features=ent.features)
    plan = (
        await db.execute(select(Plan).where(Plan.id == sub.plan_id))
    ).scalar_one_or_none()
    status_value = sub.status.value if hasattr(sub.status, "value") else str(sub.status)
    return SubscriptionOut(
        status=status_value,
        plan_id=plan.id if plan else None,
        plan_name=plan.name if plan else None,
        price_month=float(plan.price_month) if plan else None,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
        provider=sub.provider,
        has_gateway=bool(sub.provider_subscription_id),
        level=ent.level,
        limits=ent.limits,
        features=ent.features,
    )


@router.post("/checkout", response_model=UrlOut)
async def iniciar_checkout(body: CheckoutIn, db: TenantDB, user: CurrentUser) -> UrlOut:
    """Inicia a assinatura paga via checkout hospedado (owner/manager)."""
    await _require_manager(db, user)
    try:
        url = await billing_svc.start_checkout(
            user.organization_id, body.plan_id, body.cycle,
            success_url=body.success_url, cancel_url=body.cancel_url,
        )
    except billing_svc.BillingServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except BillingProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Gateway indisponível: {exc}")
    return UrlOut(url=url)


@router.post("/portal", response_model=UrlOut)
async def abrir_portal(body: PortalIn, db: TenantDB, user: CurrentUser) -> UrlOut:
    """Customer Portal (trocar cartão, upgrade/downgrade, cancelar)."""
    await _require_manager(db, user)
    try:
        url = await billing_svc.open_portal(user.organization_id, body.return_url)
    except billing_svc.BillingServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except BillingProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Gateway indisponível: {exc}")
    return UrlOut(url=url)


@router.get("/invoices", response_model=list[InvoiceOut])
async def minhas_faturas(db: TenantDB, user: CurrentUser) -> list[InvoiceOut]:
    """Faturas da própria org (RLS), mais recentes primeiro."""
    await _require_manager(db, user)
    rows = (
        await db.execute(
            select(Invoice).order_by(Invoice.created_at.desc()).limit(36)
        )
    ).scalars().all()
    return [
        InvoiceOut(
            id=i.id, number=i.number, status=i.status,
            amount_due=float(i.amount_due), amount_paid=float(i.amount_paid),
            currency=i.currency, period_start=i.period_start, period_end=i.period_end,
            due_date=i.due_date, paid_at=i.paid_at,
            hosted_invoice_url=i.hosted_invoice_url, pdf_url=i.pdf_url,
        )
        for i in rows
    ]


# ─── webhook do gateway ─────────────────────────────────────────────────────

@router.post("/webhooks/{provider_name}", status_code=status.HTTP_200_OK)
async def receber_webhook(provider_name: str, request: Request) -> dict:
    """Recebe eventos do gateway. Assinatura verificada DENTRO do provider;
    payload bruto persistido idempotente ANTES de processar (replay-safe)."""
    if provider_name != settings.billing_provider:
        # Evita processar eventos de um gateway que não é o ativo (config drift).
        raise HTTPException(status_code=404, detail="Provider de billing não ativo.")
    body = await request.body()
    try:
        summary = await billing_svc.ingest_webhook(
            provider_name, headers=dict(request.headers), body=body
        )
    except BillingProviderError as exc:
        # Assinatura inválida/segredo ausente → 400 (o gateway fará retry).
        raise HTTPException(status_code=400, detail=str(exc))
    return summary


# ─── cron interno (n8n) ─────────────────────────────────────────────────────

@internal_router.post("/run-lifecycle")
async def rodar_lifecycle(
    x_bot_token: Annotated[Optional[str], Header(alias="X-Bot-Token")] = None,
) -> dict:
    """Transições do provider manual: trial vencido → past_due → canceled."""
    if not settings.bot_api_key or not secrets_match(x_bot_token or "", settings.bot_api_key):
        raise HTTPException(status_code=401, detail="Token inválido.")
    return await billing_svc.run_lifecycle()
