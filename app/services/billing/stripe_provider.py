"""StripeBillingProvider — ÚNICO módulo que importa o SDK da Stripe (SA-D04/05).

Boas práticas aplicadas (skill oficial Stripe):
- Assinatura via Billing (Subscription) + Checkout Session `mode=subscription`;
- Customer Portal p/ autosserviço;
- Products/Prices espelhando o catálogo local (nunca o objeto `plan` deprecado);
- NUNCA enviar `payment_method_types` (payment methods dinâmicos do Dashboard);
- Dunning = Smart Retries da Stripe; aqui só normalizamos o que o webhook conta;
- Webhook SEMPRE verificado com `STRIPE_WEBHOOK_SECRET`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

import stripe

from app.core.config import settings

from .provider import BillingProvider, BillingProviderError
from .types import (
    CheckoutSession,
    InvoiceState,
    PortalSession,
    ProviderEvent,
    SubscriptionState,
)

# Versão de API alvo (pinada; ver decisions.md SA-D05).
STRIPE_API_VERSION = "2026-06-24.dahlia"

# Stripe → enum interno (subscription_status).
_STATUS_MAP = {
    "trialing": "trial",
    "active": "active",
    "past_due": "past_due",
    "canceled": "canceled",
    "unpaid": "past_due",
    "incomplete": "incomplete",
    "incomplete_expired": "canceled",
    "paused": "paused",
}


def _to_dict(obj: Any) -> dict:
    """Normaliza objetos tipados do SDK para dict PURO (recursivo).

    Os StripeObject não expõem interface de dict estável entre versões
    (`.get`/`dict()` levantam KeyError — validado em teste real contra o
    sandbox). `str(StripeObject)` é JSON completo em todas as versões; no
    SDK 15.x é a única serialização recursiva disponível. Todo retorno do
    SDK passa por aqui antes dos normalizadores `_sub_state`/`_invoice_state`.
    """
    if isinstance(obj, dict) and type(obj) is dict:
        return obj
    if hasattr(obj, "to_dict_recursive"):
        return obj.to_dict_recursive()
    import json

    return json.loads(str(obj))


def _ts(value: Optional[int]) -> Optional[datetime]:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def _money(cents: Optional[int]) -> Decimal:
    return Decimal(cents or 0) / Decimal(100)


class StripeBillingProvider(BillingProvider):
    name = "stripe"

    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or settings.stripe_secret_key
        if not key:
            raise BillingProviderError(
                "STRIPE_SECRET_KEY ausente — configure o env ou use BILLING_PROVIDER=mock"
            )
        self._client = stripe.StripeClient(key, stripe_version=STRIPE_API_VERSION)

    # ── clientes ─────────────────────────────────────────────────────────────
    async def create_customer(self, *, org_id: int, name: str, email: Optional[str]) -> str:
        customer = self._client.customers.create(
            params={
                "name": name,
                **({"email": email} if email else {}),
                "metadata": {"org_id": str(org_id)},
            }
        )
        return customer.id

    async def update_customer(self, customer_id: str, *, name=None, email=None) -> None:
        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        if email:
            params["email"] = email
        if params:
            self._client.customers.update(customer_id, params=params)

    # ── assinatura ───────────────────────────────────────────────────────────
    async def create_checkout(self, *, customer_id: str, price_id: str, success_url: str,
                              cancel_url: str, trial_days: Optional[int] = None) -> CheckoutSession:
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer": customer_id,
            # payment_method_types intencionalmente OMITIDO (métodos dinâmicos).
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if trial_days:
            params["subscription_data"] = {"trial_period_days": trial_days}
        session = self._client.checkout.sessions.create(params=params)
        return CheckoutSession(url=session.url)

    async def create_portal(self, *, customer_id: str, return_url: str) -> PortalSession:
        session = self._client.billing_portal.sessions.create(
            params={"customer": customer_id, "return_url": return_url}
        )
        return PortalSession(url=session.url)

    async def create_subscription(self, *, customer_id: str, price_id: str,
                                  trial_days: Optional[int] = None) -> SubscriptionState:
        params: dict[str, Any] = {
            "customer": customer_id,
            "items": [{"price": price_id}],
        }
        if trial_days:
            params["trial_period_days"] = trial_days
        sub = self._client.subscriptions.create(params=params)
        return self._sub_state(_to_dict(sub))

    async def update_subscription(self, provider_subscription_id: str, *,
                                  price_id: str) -> SubscriptionState:
        sub = _to_dict(self._client.subscriptions.retrieve(provider_subscription_id))
        item_id = sub["items"]["data"][0]["id"]
        updated = self._client.subscriptions.update(
            provider_subscription_id,
            params={
                "items": [{"id": item_id, "price": price_id}],
                "proration_behavior": "create_prorations",
            },
        )
        return self._sub_state(_to_dict(updated))

    async def cancel_subscription(self, provider_subscription_id: str, *,
                                  at_period_end: bool = True) -> SubscriptionState:
        if at_period_end:
            sub = self._client.subscriptions.update(
                provider_subscription_id, params={"cancel_at_period_end": True}
            )
        else:
            sub = self._client.subscriptions.cancel(provider_subscription_id)
        return self._sub_state(_to_dict(sub))

    async def reactivate_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        sub = self._client.subscriptions.update(
            provider_subscription_id, params={"cancel_at_period_end": False}
        )
        return self._sub_state(_to_dict(sub))

    async def pause_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        sub = self._client.subscriptions.update(
            provider_subscription_id,
            params={"pause_collection": {"behavior": "void"}},
        )
        state = self._sub_state(_to_dict(sub))
        state.status, state.paused = "paused", True
        return state

    async def resume_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        sub = self._client.subscriptions.update(
            provider_subscription_id, params={"pause_collection": ""}
        )
        return self._sub_state(_to_dict(sub))

    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        return self._sub_state(_to_dict(self._client.subscriptions.retrieve(provider_subscription_id)))

    async def get_invoices(self, customer_id: str, *, limit: int = 24) -> list[InvoiceState]:
        invoices = self._client.invoices.list(params={"customer": customer_id, "limit": limit})
        return [self._invoice_state(_to_dict(i)) for i in invoices.data]

    async def refund_payment(self, provider_payment_id: str, *, amount=None) -> None:
        params: dict[str, Any] = {"payment_intent": provider_payment_id}
        if amount is not None:
            params["amount"] = int(Decimal(amount) * 100)
        self._client.refunds.create(params=params)

    # ── catálogo ─────────────────────────────────────────────────────────────
    async def sync_plan(self, *, plan_slug: str, plan_name: str, product_id: Optional[str],
                        prices: list[dict]) -> tuple[str, dict[str, str]]:
        if product_id:
            self._client.products.update(product_id, params={"name": plan_name})
            pid = product_id
        else:
            pid = self._client.products.create(
                params={"name": plan_name, "metadata": {"plan_slug": plan_slug}}
            ).id
        out: dict[str, str] = {}
        interval = {"monthly": "month", "yearly": "year"}
        for price in prices:
            existing = price.get("provider_price_id")
            if existing:
                out[price["cycle"]] = existing  # Prices são imutáveis na Stripe
                continue
            created = self._client.prices.create(
                params={
                    "product": pid,
                    "currency": price.get("currency", "brl"),
                    "unit_amount": int(Decimal(str(price["amount"])) * 100),
                    "recurring": {"interval": interval[price["cycle"]]},
                    "metadata": {"plan_slug": plan_slug, "cycle": price["cycle"]},
                }
            )
            out[price["cycle"]] = created.id
        return pid, out

    # ── webhooks ─────────────────────────────────────────────────────────────
    def parse_webhook(self, *, headers: Mapping[str, str], body: bytes) -> list[ProviderEvent]:
        secret = settings.stripe_webhook_secret
        if not secret:
            raise BillingProviderError("STRIPE_WEBHOOK_SECRET ausente")
        signature = headers.get("stripe-signature") or headers.get("Stripe-Signature") or ""
        try:
            event = stripe.Webhook.construct_event(body, signature, secret)
        except Exception as exc:  # assinatura inválida/payload corrompido
            raise BillingProviderError(f"webhook rejeitado: {exc}") from exc
        # Normalizamos sobre dict PURO (mesma razão do _to_dict).
        return [self._normalize_event(_to_dict(event))]

    def parse_payload(self, payload: dict) -> ProviderEvent:
        return self._normalize_event(payload)

    def _normalize_event(self, event: Any) -> ProviderEvent:
        etype: str = event["type"]
        obj = event["data"]["object"]
        base = dict(provider=self.name, event_id=event["id"], event_type=etype)

        if etype.startswith("customer.subscription."):
            state = self._sub_state(obj)
            return ProviderEvent(
                **base, kind="subscription_updated",
                provider_customer_id=state.provider_customer_id, subscription=state,
            )
        if etype == "checkout.session.completed" and obj.get("subscription"):
            sub = self._client.subscriptions.retrieve(obj["subscription"])
            state = self._sub_state(_to_dict(sub))
            return ProviderEvent(
                **base, kind="subscription_updated",
                provider_customer_id=state.provider_customer_id, subscription=state,
            )
        if etype.startswith("invoice."):
            inv = self._invoice_state(obj)
            return ProviderEvent(
                **base, kind="invoice_updated",
                provider_customer_id=inv.provider_customer_id, invoice=inv,
            )
        if etype == "charge.refunded":
            from .types import PaymentState

            payment = PaymentState(
                provider_payment_id=obj.get("payment_intent") or obj["id"],
                status="refunded" if obj.get("refunded") else "partially_refunded",
                amount=_money(obj.get("amount")),
                currency=obj.get("currency", "brl"),
                provider_customer_id=obj.get("customer"),
                refunded_at=_ts(event.get("created")),
            )
            return ProviderEvent(
                **base, kind="payment_updated",
                provider_customer_id=payment.provider_customer_id, payment=payment,
            )
        return ProviderEvent(**base, kind="ignored")

    # ── normalizadores ───────────────────────────────────────────────────────
    def _sub_state(self, sub: Any) -> SubscriptionState:
        items = sub.get("items", {}).get("data", [])
        price_id = items[0]["price"]["id"] if items else None
        # API dahlia: período vive no item; fallback ao topo (versões antigas).
        item0 = items[0] if items else {}
        period_start = item0.get("current_period_start") or sub.get("current_period_start")
        period_end = item0.get("current_period_end") or sub.get("current_period_end")
        paused = bool(sub.get("pause_collection"))
        status = _STATUS_MAP.get(sub.get("status"), "incomplete")
        if paused:
            status = "paused"
        return SubscriptionState(
            provider_subscription_id=sub["id"],
            status=status,
            provider_customer_id=sub.get("customer"),
            provider_price_id=price_id,
            current_period_start=_ts(period_start),
            current_period_end=_ts(period_end),
            cancel_at_period_end=bool(sub.get("cancel_at_period_end")),
            trial_end=_ts(sub.get("trial_end")),
            canceled_at=_ts(sub.get("canceled_at")),
            paused=paused,
        )

    def _invoice_state(self, inv: Any) -> InvoiceState:
        # API dahlia: vínculo com a assinatura via parent.subscription_details.
        parent = inv.get("parent") or {}
        sub_details = parent.get("subscription_details") or {}
        sub_id = sub_details.get("subscription") or inv.get("subscription")
        lines = inv.get("lines", {}).get("data", [])
        period = (lines[0].get("period") if lines else None) or inv.get("period") or {}
        return InvoiceState(
            provider_invoice_id=inv["id"],
            status=inv.get("status") or "open",
            amount_due=_money(inv.get("amount_due")),
            amount_paid=_money(inv.get("amount_paid")),
            currency=inv.get("currency", "brl"),
            number=inv.get("number"),
            provider_customer_id=inv.get("customer"),
            provider_subscription_id=sub_id,
            period_start=_ts(period.get("start")),
            period_end=_ts(period.get("end")),
            due_date=_ts(inv.get("due_date")),
            paid_at=_ts((inv.get("status_transitions") or {}).get("paid_at")),
            hosted_invoice_url=inv.get("hosted_invoice_url"),
            pdf_url=inv.get("invoice_pdf"),
            attempt_count=inv.get("attempt_count"),
            next_retry_at=_ts(inv.get("next_payment_attempt")),
            last_error_code=(inv.get("last_finalization_error") or {}).get("code"),
            last_error_message=(inv.get("last_finalization_error") or {}).get("message"),
        )
