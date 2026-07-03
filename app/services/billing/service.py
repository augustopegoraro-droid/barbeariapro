"""SubscriptionService — regra de negócio do billing (único chamador do provider).

Padrões do repo respeitados:
- Sessões org-escopadas via helper (`AsyncSessionLocal` + `set_current_org`),
  nunca a sessão do request de plataforma (molde D-55).
- Resolução cross-org só por SECURITY DEFINER (webhooks: customer→org).
- Todo efeito relevante vira linha em `billing_events` (append-only).

Invariante de negócio: uma org tem UMA assinatura operativa — a mais recente
(`created_at DESC`), mesma regra do restante do sistema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from models import (
    BillingCredit,
    BillingCustomer,
    BillingEvent,
    BillingPayment,
    Coupon,
    Discount,
    Invoice,
    Organization,
    PaymentAttempt,
    Plan,
    PlanPrice,
    Subscription,
    WebhookEvent,
)

from .registry import get_billing_provider
from .types import InvoiceState, PaymentState, ProviderEvent, SubscriptionState

_logger = logging.getLogger(__name__)


class BillingServiceError(Exception):
    """Erro de regra de negócio (mensagem segura p/ devolver ao cliente)."""

    def __init__(self, detail: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _latest_subscription(session: AsyncSession, org_id: int) -> Optional[Subscription]:
    return (
        await session.execute(
            select(Subscription)
            .where(Subscription.organization_id == org_id)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def record_event(
    session: AsyncSession,
    org_id: int,
    event_type: str,
    *,
    actor_type: str = "system",
    actor_id: Optional[int] = None,
    actor_label: Optional[str] = None,
    subscription_id: Optional[int] = None,
    invoice_id: Optional[int] = None,
    payload: Optional[dict] = None,
) -> None:
    session.add(
        BillingEvent(
            organization_id=org_id,
            subscription_id=subscription_id,
            invoice_id=invoice_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_label=actor_label,
            payload=payload or {},
        )
    )


async def _ensure_customer(session: AsyncSession, org: Organization, provider_name: str) -> BillingCustomer:
    existing = (
        await session.execute(
            select(BillingCustomer).where(
                BillingCustomer.organization_id == org.id,
                BillingCustomer.provider == provider_name,
            )
        )
    ).scalars().first()
    if existing:
        return existing
    provider = get_billing_provider(provider_name)
    customer_id = await provider.create_customer(org_id=org.id, name=org.name, email=org.email)
    customer = BillingCustomer(
        organization_id=org.id, provider=provider_name, provider_customer_id=customer_id
    )
    session.add(customer)
    await session.flush()
    return customer


async def _ensure_price(session: AsyncSession, plan: Plan, cycle: str, provider_name: str) -> PlanPrice:
    """Preço ativo do plano no ciclo, com id externo garantido (sync sob demanda)."""
    price = (
        await session.execute(
            select(PlanPrice).where(
                PlanPrice.plan_id == plan.id,
                PlanPrice.cycle == cycle,
                PlanPrice.active.is_(True),
            )
        )
    ).scalars().first()
    if price is None:
        raise BillingServiceError(f"Plano sem preço {cycle} ativo.", status_code=400)
    if provider_name != "manual" and not price.provider_price_id:
        provider = get_billing_provider(provider_name)
        product_id, price_ids = await provider.sync_plan(
            plan_slug=plan.slug or f"plan-{plan.id}",
            plan_name=plan.name,
            product_id=plan.stripe_product_id if provider_name == "stripe" else None,
            prices=[{
                "cycle": price.cycle,
                "amount": price.amount,
                "currency": price.currency,
                "provider_price_id": price.provider_price_id,
            }],
        )
        if provider_name == "stripe":
            plan.stripe_product_id = product_id
        price.provider_price_id = price_ids.get(cycle)
        await session.flush()
    return price


# ─── fluxo do tenant ─────────────────────────────────────────────────────────

async def start_checkout(
    org_id: int, plan_id: int, cycle: str, success_url: str, cancel_url: str
) -> str:
    """Inicia assinatura via checkout hospedado. Devolve a URL de pagamento."""
    provider_name = settings.billing_provider
    provider = get_billing_provider(provider_name)
    events: list[ProviderEvent] = []
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            org = (
                await session.execute(select(Organization).where(Organization.id == org_id))
            ).scalar_one_or_none()
            if org is None:
                raise BillingServiceError("Org não encontrada.", status_code=404)
            plan = (
                await session.execute(select(Plan).where(Plan.id == plan_id, Plan.is_active.is_(True)))
            ).scalar_one_or_none()
            if plan is None:
                raise BillingServiceError("Plano inexistente ou inativo.", status_code=400)

            sub = await _latest_subscription(session, org_id)
            if sub is not None and sub.provider_subscription_id and sub.status.value in ("active", "trial", "past_due", "paused"):
                raise BillingServiceError(
                    "Já existe assinatura no gateway — use o portal para alterações."
                )

            customer = await _ensure_customer(session, org, provider_name)
            price = await _ensure_price(session, plan, cycle, provider_name)
            checkout = await provider.create_checkout(
                customer_id=customer.provider_customer_id,
                price_id=price.provider_price_id or f"manual_{plan.id}_{cycle}",
                success_url=success_url,
                cancel_url=cancel_url,
            )
            await record_event(
                session, org_id, "checkout_started", actor_type="tenant",
                payload={"plan_id": plan_id, "cycle": cycle, "provider": provider_name},
            )
            events = checkout.events
    # Mock: aplica na hora os eventos que a Stripe mandaria por webhook.
    for event in events:
        await apply_provider_event(event)
    return checkout.url


async def open_portal(org_id: int, return_url: str) -> str:
    provider_name = settings.billing_provider
    provider = get_billing_provider(provider_name)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            org = (
                await session.execute(select(Organization).where(Organization.id == org_id))
            ).scalar_one_or_none()
            if org is None:
                raise BillingServiceError("Org não encontrada.", status_code=404)
            customer = await _ensure_customer(session, org, provider_name)
    portal = await provider.create_portal(
        customer_id=customer.provider_customer_id, return_url=return_url
    )
    return portal.url


# ─── ações administrativas (superadmin) ──────────────────────────────────────

async def _admin_subscription_action(
    org_id: int,
    action: str,
    actor: Mapping[str, Any],
    *,
    mutate_local,
    provider_call=None,
    payload: Optional[dict] = None,
) -> None:
    """Esqueleto das ações: aplica no gateway (se houver) e no estado local."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            sub = await _latest_subscription(session, org_id)
            if sub is None:
                raise BillingServiceError("Org sem assinatura.", status_code=404)
            state: Optional[SubscriptionState] = None
            if provider_call is not None and sub.provider_subscription_id:
                provider = get_billing_provider(sub.provider)
                state = await provider_call(provider, sub.provider_subscription_id)
            mutate_local(sub, state)
            sub.updated_at = _now()
            await record_event(
                session, org_id, action,
                actor_type=str(actor.get("type", "platform_admin")),
                actor_id=actor.get("id"), actor_label=actor.get("label"),
                subscription_id=sub.id, payload=payload or {},
            )


async def cancel_subscription(org_id: int, *, at_period_end: bool, actor: Mapping[str, Any]) -> None:
    def mutate(sub: Subscription, state: Optional[SubscriptionState]) -> None:
        if at_period_end:
            sub.cancel_at_period_end = True
        else:
            sub.status = "canceled"
            sub.canceled_at = _now()

    await _admin_subscription_action(
        org_id, "subscription_canceled", actor,
        mutate_local=mutate,
        provider_call=lambda p, sid: p.cancel_subscription(sid, at_period_end=at_period_end),
        payload={"at_period_end": at_period_end},
    )


async def reactivate_subscription(org_id: int, *, actor: Mapping[str, Any]) -> None:
    def mutate(sub: Subscription, state: Optional[SubscriptionState]) -> None:
        sub.cancel_at_period_end = False
        if sub.status.value == "canceled":
            sub.status = "active"
            sub.canceled_at = None
            if sub.current_period_end <= _now():
                sub.current_period_start = _now()
                sub.current_period_end = _now() + timedelta(days=30)

    await _admin_subscription_action(
        org_id, "subscription_reactivated", actor,
        mutate_local=mutate,
        provider_call=lambda p, sid: p.reactivate_subscription(sid),
    )


async def pause_subscription(org_id: int, *, actor: Mapping[str, Any]) -> None:
    def mutate(sub: Subscription, state: Optional[SubscriptionState]) -> None:
        sub.status = "paused"
        sub.paused_at = _now()

    await _admin_subscription_action(
        org_id, "subscription_paused", actor,
        mutate_local=mutate,
        provider_call=lambda p, sid: p.pause_subscription(sid),
    )


async def resume_subscription(org_id: int, *, actor: Mapping[str, Any]) -> None:
    def mutate(sub: Subscription, state: Optional[SubscriptionState]) -> None:
        sub.status = "active"
        sub.paused_at = None
        sub.resumes_at = None

    await _admin_subscription_action(
        org_id, "subscription_resumed", actor,
        mutate_local=mutate,
        provider_call=lambda p, sid: p.resume_subscription(sid),
    )


async def change_plan(org_id: int, plan_id: int, *, cycle: str = "monthly",
                      actor: Mapping[str, Any]) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            sub = await _latest_subscription(session, org_id)
            if sub is None:
                raise BillingServiceError("Org sem assinatura.", status_code=404)
            plan = (
                await session.execute(select(Plan).where(Plan.id == plan_id, Plan.is_active.is_(True)))
            ).scalar_one_or_none()
            if plan is None:
                raise BillingServiceError("Plano inexistente ou inativo.", status_code=400)
            old_plan_id = sub.plan_id
            if sub.provider_subscription_id:
                provider = get_billing_provider(sub.provider)
                price = await _ensure_price(session, plan, cycle, sub.provider)
                await provider.update_subscription(
                    sub.provider_subscription_id, price_id=price.provider_price_id
                )
            sub.plan_id = plan_id
            sub.updated_at = _now()
            await record_event(
                session, org_id, "plan_changed",
                actor_type=str(actor.get("type", "platform_admin")),
                actor_id=actor.get("id"), actor_label=actor.get("label"),
                subscription_id=sub.id,
                payload={"from_plan_id": old_plan_id, "to_plan_id": plan_id, "cycle": cycle},
            )


async def grant_free_days(org_id: int, days: int, *, actor: Mapping[str, Any]) -> None:
    """Estende o período local. Com gateway, a cobrança real não muda —
    registrado no evento (`provider_extended: false`); desconto real = cupom."""
    if days <= 0 or days > 365:
        raise BillingServiceError("Dias grátis deve estar entre 1 e 365.", status_code=400)

    def mutate(sub: Subscription, state: Optional[SubscriptionState]) -> None:
        base = max(sub.current_period_end, _now())
        sub.current_period_end = base + timedelta(days=days)
        if sub.trial_end is not None:
            sub.trial_end = sub.current_period_end

    await _admin_subscription_action(
        org_id, "free_days_granted", actor, mutate_local=mutate,
        payload={"days": days, "provider_extended": False},
    )


async def apply_coupon(org_id: int, code: str, *, reason: Optional[str],
                       actor: Mapping[str, Any]) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            coupon = (
                await session.execute(
                    select(Coupon).where(Coupon.code == code.strip(), Coupon.active.is_(True))
                )
            ).scalar_one_or_none()
            if coupon is None:
                raise BillingServiceError("Cupom inexistente ou inativo.", status_code=400)
            if coupon.valid_until is not None and coupon.valid_until < _now():
                raise BillingServiceError("Cupom expirado.", status_code=400)
            if coupon.max_redemptions is not None and coupon.times_redeemed >= coupon.max_redemptions:
                raise BillingServiceError("Cupom esgotado.", status_code=400)
            sub = await _latest_subscription(session, org_id)
            ends_at = None
            if coupon.duration == "once":
                ends_at = _now() + timedelta(days=31)
            elif coupon.duration == "repeating" and coupon.duration_months:
                ends_at = _now() + timedelta(days=31 * coupon.duration_months)
            session.add(
                Discount(
                    organization_id=org_id,
                    subscription_id=sub.id if sub else None,
                    coupon_id=coupon.id,
                    ends_at=ends_at,
                    reason=reason,
                    created_by_admin_id=actor.get("id"),
                )
            )
            coupon.times_redeemed += 1
            await record_event(
                session, org_id, "coupon_applied",
                actor_type=str(actor.get("type", "platform_admin")),
                actor_id=actor.get("id"), actor_label=actor.get("label"),
                subscription_id=sub.id if sub else None,
                payload={"coupon_code": coupon.code},
            )


async def grant_credit(org_id: int, amount: Decimal, *, reason: Optional[str],
                       actor: Mapping[str, Any]) -> None:
    if amount == 0:
        raise BillingServiceError("Valor de crédito não pode ser zero.", status_code=400)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            session.add(
                BillingCredit(
                    organization_id=org_id, amount=amount, reason=reason,
                    source="admin", created_by_admin_id=actor.get("id"),
                )
            )
            await record_event(
                session, org_id, "credit_granted",
                actor_type=str(actor.get("type", "platform_admin")),
                actor_id=actor.get("id"), actor_label=actor.get("label"),
                payload={"amount": str(amount)},
            )


# ─── webhooks / eventos do gateway ───────────────────────────────────────────

async def ingest_webhook(provider_name: str, headers: Mapping[str, str], body: bytes) -> dict:
    """Verifica assinatura, persiste bruto (idempotente) e processa cada evento."""
    import json

    provider = get_billing_provider(provider_name)
    events = provider.parse_webhook(headers=headers, body=body)  # levanta se inválido
    try:
        raw_payload = json.loads(body.decode("utf-8"))
    except Exception:  # payload já validado pela assinatura; fallback defensivo
        raw_payload = {}

    received = processed = duplicated = failed = 0
    for event in events:
        received += 1
        async with AsyncSessionLocal() as session:
            async with session.begin():
                inserted = (
                    await session.execute(
                        pg_insert(WebhookEvent)
                        .values(
                            provider=event.provider,
                            event_id=event.event_id,
                            event_type=event.event_type,
                            # Payload BRUTO: é o que permite reprocessar depois.
                            payload=raw_payload,
                            status="received",
                        )
                        .on_conflict_do_nothing(index_elements=["provider", "event_id"])
                        .returning(WebhookEvent.id)
                    )
                ).scalar_one_or_none()
        if inserted is None:
            duplicated += 1  # replay do gateway — já processado
            continue
        try:
            org_id = await apply_provider_event(event)
            await _mark_webhook(inserted, "processed" if event.kind != "ignored" else "skipped", org_id=org_id)
            processed += 1
        except Exception as exc:  # noqa: BLE001 — evento ruim não pode derrubar o lote
            _logger.exception("webhook %s falhou", event.event_id)
            await _mark_webhook(inserted, "failed", error=str(exc)[:500])
            failed += 1
    return {"received": received, "processed": processed, "duplicated": duplicated, "failed": failed}


async def reprocess_webhook_event(webhook_event_id: int) -> dict:
    """Reprocessa um evento persistido (falho/skipped) a partir do payload bruto."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(WebhookEvent).where(WebhookEvent.id == webhook_event_id)
            )
        ).scalars().first()
    if row is None:
        raise BillingServiceError("Evento de webhook não encontrado.", status_code=404)
    provider = get_billing_provider(row.provider)
    event = provider.parse_payload(row.payload)
    try:
        org_id = await apply_provider_event(event)
        await _mark_webhook(row.id, "processed" if event.kind != "ignored" else "skipped",
                            org_id=org_id)
        return {"status": "processed", "organization_id": org_id}
    except Exception as exc:  # noqa: BLE001
        await _mark_webhook(row.id, "failed", error=str(exc)[:500])
        raise BillingServiceError(f"Reprocesso falhou: {exc}", status_code=422)


async def _mark_webhook(webhook_id: int, status: str, *, org_id: Optional[int] = None,
                        error: Optional[str] = None) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                update(WebhookEvent)
                .where(WebhookEvent.id == webhook_id)
                .values(
                    status=status,
                    organization_id=org_id,
                    error=error,
                    attempts=WebhookEvent.attempts + 1,
                    processed_at=_now(),
                )
            )


async def _resolve_org(event: ProviderEvent) -> Optional[int]:
    """Customer/assinatura externa → org, via SECURITY DEFINER (sem GUC)."""
    async with AsyncSessionLocal() as session:
        if event.provider_customer_id:
            org_id = (
                await session.execute(
                    text("SELECT app_billing_org_by_customer(:p, :c)"),
                    {"p": event.provider, "c": event.provider_customer_id},
                )
            ).scalar_one_or_none()
            if org_id is not None:
                return int(org_id)
        sid = None
        if event.subscription is not None:
            sid = event.subscription.provider_subscription_id
        elif event.invoice is not None:
            sid = event.invoice.provider_subscription_id
        if sid:
            org_id = (
                await session.execute(
                    text("SELECT app_billing_org_by_provider_subscription(:p, :s)"),
                    {"p": event.provider, "s": sid},
                )
            ).scalar_one_or_none()
            if org_id is not None:
                return int(org_id)
    return None


async def apply_provider_event(event: ProviderEvent) -> Optional[int]:
    """Aplica um evento normalizado ao domínio. Devolve a org afetada."""
    if event.kind == "ignored":
        return None
    org_id = await _resolve_org(event)
    if org_id is None:
        raise BillingServiceError(
            f"evento {event.event_id}: customer/assinatura não mapeados a nenhuma org",
            status_code=422,
        )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            if event.kind == "subscription_updated" and event.subscription:
                await _apply_subscription_state(session, org_id, event)
            elif event.kind == "invoice_updated" and event.invoice:
                await _apply_invoice_state(session, org_id, event)
            elif event.kind == "payment_updated" and event.payment:
                await _apply_payment_state(session, org_id, event)
    return org_id


async def _apply_subscription_state(session: AsyncSession, org_id: int, event: ProviderEvent) -> None:
    state = event.subscription
    assert state is not None
    # Webhooks chegam FORA DE ORDEM (comportamento documentado da Stripe): o
    # payload pode ser snapshot antigo e regravar estado obsoleto por cima do
    # atual (visto no sandbox: resume seguido de webhook atrasado do pause).
    # Regra canônica: rebuscar o estado ATUAL no gateway e aplicar esse;
    # payload do evento é fallback se o gateway estiver inacessível.
    try:
        provider = get_billing_provider(event.provider)
        state = await provider.get_subscription(state.provider_subscription_id)
    except Exception as exc:  # noqa: BLE001 — degrada para o payload do evento
        _logger.warning(
            "refresh da assinatura %s no gateway falhou (%s) — aplicando payload do evento",
            state.provider_subscription_id, exc,
        )
    sub = (
        await session.execute(
            select(Subscription).where(
                Subscription.provider == event.provider,
                Subscription.provider_subscription_id == state.provider_subscription_id,
            )
        )
    ).scalars().first()
    if sub is None:
        # 1ª notícia desta assinatura: "reivindica" a assinatura local mais
        # recente sem vínculo de gateway (fluxo pós-checkout) ou cria uma nova.
        sub = await _latest_subscription(session, org_id)
        if sub is None or sub.provider_subscription_id:
            plan_id = await _plan_by_price(session, event.provider, state.provider_price_id)
            if plan_id is None:
                raise BillingServiceError(
                    f"price {state.provider_price_id} sem plano local mapeado", status_code=422
                )
            sub = Subscription(
                organization_id=org_id,
                plan_id=plan_id,
                current_period_start=state.current_period_start or _now(),
                current_period_end=state.current_period_end or (_now() + timedelta(days=30)),
            )
            session.add(sub)
            await session.flush()
        sub.provider = event.provider
        sub.provider_subscription_id = state.provider_subscription_id
        sub.provider_customer_id = state.provider_customer_id

    plan_id = await _plan_by_price(session, event.provider, state.provider_price_id)
    if plan_id is not None:
        sub.plan_id = plan_id
    old_status = sub.status.value if hasattr(sub.status, "value") else str(sub.status)
    sub.status = state.status
    if state.current_period_start:
        sub.current_period_start = state.current_period_start
    if state.current_period_end:
        sub.current_period_end = state.current_period_end
    sub.cancel_at_period_end = state.cancel_at_period_end
    sub.trial_end = state.trial_end
    sub.canceled_at = state.canceled_at
    sub.paused_at = _now() if state.paused and sub.paused_at is None else (
        sub.paused_at if state.paused else None
    )
    sub.updated_at = _now()
    await record_event(
        session, org_id, "provider_subscription_updated", actor_type="provider",
        actor_label=event.provider, subscription_id=sub.id,
        payload={
            "event": event.event_type, "from_status": old_status, "to_status": state.status,
            "provider_subscription_id": state.provider_subscription_id,
        },
    )


async def _plan_by_price(session: AsyncSession, provider: str, price_id: Optional[str]) -> Optional[int]:
    if not price_id:
        return None
    return (
        await session.execute(
            select(PlanPrice.plan_id).where(PlanPrice.provider_price_id == price_id)
        )
    ).scalar_one_or_none()


async def _apply_invoice_state(session: AsyncSession, org_id: int, event: ProviderEvent) -> None:
    state: InvoiceState = event.invoice  # type: ignore[assignment]
    sub_id = None
    if state.provider_subscription_id:
        sub_id = (
            await session.execute(
                select(Subscription.id).where(
                    Subscription.provider == event.provider,
                    Subscription.provider_subscription_id == state.provider_subscription_id,
                )
            )
        ).scalar_one_or_none()

    values = dict(
        organization_id=org_id,
        subscription_id=sub_id,
        provider=event.provider,
        provider_invoice_id=state.provider_invoice_id,
        number=state.number,
        status=state.status,
        amount_due=state.amount_due,
        amount_paid=state.amount_paid,
        currency=state.currency,
        period_start=state.period_start,
        period_end=state.period_end,
        due_date=state.due_date,
        paid_at=state.paid_at,
        hosted_invoice_url=state.hosted_invoice_url,
        pdf_url=state.pdf_url,
        updated_at=_now(),
    )
    invoice_id = (
        await session.execute(
            pg_insert(Invoice)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["provider", "provider_invoice_id"],
                set_={k: v for k, v in values.items() if k not in ("organization_id", "provider", "provider_invoice_id")},
            )
            .returning(Invoice.id)
        )
    ).scalar_one()

    # Dunning: cada invoice.payment_failed vira uma tentativa (idempotente).
    if state.attempt_count and state.status != "paid":
        attempt = dict(
            organization_id=org_id,
            invoice_id=invoice_id,
            attempt_number=state.attempt_count,
            status="failed",
            provider_error_code=state.last_error_code,
            provider_error_message=state.last_error_message,
            attempted_at=_now(),
            next_retry_at=state.next_retry_at,
        )
        await session.execute(
            pg_insert(PaymentAttempt)
            .values(**attempt)
            .on_conflict_do_update(
                index_elements=["invoice_id", "attempt_number"],
                set_={"status": "failed", "next_retry_at": state.next_retry_at},
            )
        )
    if state.status == "paid":
        payment = dict(
            organization_id=org_id,
            invoice_id=invoice_id,
            provider=event.provider,
            provider_payment_id=f"forinv_{state.provider_invoice_id}",
            amount=state.amount_paid,
            currency=state.currency,
            status="succeeded",
            paid_at=state.paid_at or _now(),
        )
        await session.execute(
            pg_insert(BillingPayment)
            .values(**payment)
            .on_conflict_do_update(
                index_elements=["provider", "provider_payment_id"],
                set_={"status": "succeeded", "amount": state.amount_paid, "paid_at": payment["paid_at"]},
            )
        )
    await record_event(
        session, org_id, f"provider_invoice_{state.status}", actor_type="provider",
        actor_label=event.provider, invoice_id=invoice_id,
        payload={"event": event.event_type, "amount_due": str(state.amount_due),
                 "attempt_count": state.attempt_count},
    )


async def _apply_payment_state(session: AsyncSession, org_id: int, event: ProviderEvent) -> None:
    state: PaymentState = event.payment  # type: ignore[assignment]
    values = dict(
        organization_id=org_id,
        provider=event.provider,
        provider_payment_id=state.provider_payment_id,
        amount=state.amount,
        currency=state.currency,
        status=state.status,
        method=state.method,
        failure_code=state.failure_code,
        failure_message=state.failure_message,
        paid_at=state.paid_at,
        refunded_at=state.refunded_at,
    )
    await session.execute(
        pg_insert(BillingPayment)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["provider", "provider_payment_id"],
            set_={"status": state.status, "refunded_at": state.refunded_at},
        )
    )
    await record_event(
        session, org_id, f"provider_payment_{state.status}", actor_type="provider",
        actor_label=event.provider, payload={"event": event.event_type, "amount": str(state.amount)},
    )


# ─── ciclo de vida (provider manual) ─────────────────────────────────────────

async def run_lifecycle(
    now: Optional[datetime] = None, *, only_org_ids: Optional[list[int]] = None
) -> dict:
    """Transições do provider `manual` (gateway cuida das dele via webhook):
    trial vencido → past_due · past_due além da carência → canceled ·
    cancel_at_period_end vencido → canceled. Chamado por cron (n8n).
    `only_org_ids` restringe o alcance (reprocesso direcionado/testes)."""
    now = now or _now()
    grace = timedelta(days=settings.billing_grace_days_past_due)
    moved = {"to_past_due": 0, "to_canceled": 0}

    async with AsyncSessionLocal() as plain:
        org_ids = [
            int(r) for r in (
                await plain.execute(text("SELECT app_platform_active_org_ids()"))
            ).scalars().all()
        ]
    if only_org_ids is not None:
        org_ids = [o for o in org_ids if o in set(only_org_ids)]

    for org_id in org_ids:
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await set_current_org(session, org_id)
                    sub = await _latest_subscription(session, org_id)
                    if sub is None or sub.provider != "manual":
                        continue
                    status = sub.status.value if hasattr(sub.status, "value") else str(sub.status)
                    if status in ("trial", "active") and sub.cancel_at_period_end and sub.current_period_end <= now:
                        sub.status, sub.canceled_at = "canceled", now
                        moved["to_canceled"] += 1
                        await record_event(session, org_id, "lifecycle_canceled_at_period_end",
                                           subscription_id=sub.id)
                    elif status == "trial" and sub.current_period_end <= now:
                        sub.status = "past_due"
                        moved["to_past_due"] += 1
                        await record_event(session, org_id, "lifecycle_trial_expired",
                                           subscription_id=sub.id,
                                           payload={"period_end": sub.current_period_end.isoformat()})
                    elif status == "past_due" and sub.current_period_end + grace <= now:
                        sub.status, sub.canceled_at = "canceled", now
                        moved["to_canceled"] += 1
                        await record_event(session, org_id, "lifecycle_canceled_after_grace",
                                           subscription_id=sub.id,
                                           payload={"grace_days": settings.billing_grace_days_past_due})
                    if sub in session.dirty:
                        sub.updated_at = now
        except Exception as exc:  # noqa: BLE001 — uma org ruim não para o job
            _logger.warning("lifecycle falhou para org %s: %s", org_id, exc)
    return moved
