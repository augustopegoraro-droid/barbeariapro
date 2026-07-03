"""MockBillingProvider — gateway de desenvolvimento/testes (sem rede).

Simula o comportamento essencial da Stripe de forma determinística e
SÍNCRONA: `create_checkout` devolve, além da URL, os eventos que a Stripe
mandaria por webhook (assinatura ativa + fatura paga) — o service os aplica na
hora. Estado em memória por processo (suficiente p/ dev e testes).
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping, Optional

from .provider import BillingProvider, BillingProviderError
from .types import (
    CheckoutSession,
    InvoiceState,
    PortalSession,
    ProviderEvent,
    SubscriptionState,
)

_ids = itertools.count(1)
# Estado por processo: {sub_id: SubscriptionState}, {customer_id: [InvoiceState]}
_subs: dict[str, SubscriptionState] = {}
_invoices: dict[str, list[InvoiceState]] = {}
_prices: dict[str, Decimal] = {}  # price_id -> amount


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MockBillingProvider(BillingProvider):
    name = "mock"

    async def create_customer(self, *, org_id: int, name: str, email: Optional[str]) -> str:
        return f"mock_cus_{org_id}"

    async def update_customer(self, customer_id: str, *, name=None, email=None) -> None:
        return None

    def _subscription(self, customer_id: str, price_id: str,
                      trial_days: Optional[int]) -> SubscriptionState:
        sid = f"mock_sub_{next(_ids)}"
        now = _now()
        status = "trial" if trial_days else "active"
        state = SubscriptionState(
            provider_subscription_id=sid,
            status=status,
            provider_customer_id=customer_id,
            provider_price_id=price_id,
            current_period_start=now,
            current_period_end=now + timedelta(days=trial_days or 30),
            trial_end=(now + timedelta(days=trial_days)) if trial_days else None,
        )
        _subs[sid] = state
        return state

    def _paid_invoice(self, state: SubscriptionState) -> InvoiceState:
        iid = f"mock_in_{next(_ids)}"
        amount = _prices.get(state.provider_price_id or "", Decimal("0"))
        inv = InvoiceState(
            provider_invoice_id=iid,
            status="paid",
            amount_due=amount,
            amount_paid=amount,
            number=iid.upper(),
            provider_customer_id=state.provider_customer_id,
            provider_subscription_id=state.provider_subscription_id,
            period_start=state.current_period_start,
            period_end=state.current_period_end,
            paid_at=_now(),
            hosted_invoice_url=f"https://mock.billing/invoices/{iid}",
        )
        _invoices.setdefault(state.provider_customer_id or "", []).append(inv)
        return inv

    async def create_checkout(self, *, customer_id: str, price_id: str, success_url: str,
                              cancel_url: str, trial_days: Optional[int] = None) -> CheckoutSession:
        state = self._subscription(customer_id, price_id, trial_days)
        events: list[ProviderEvent] = [
            ProviderEvent(
                provider=self.name,
                event_id=f"mock_evt_{next(_ids)}",
                event_type="customer.subscription.created",
                kind="subscription_updated",
                provider_customer_id=customer_id,
                subscription=state,
            )
        ]
        if not trial_days:
            inv = self._paid_invoice(state)
            events.append(
                ProviderEvent(
                    provider=self.name,
                    event_id=f"mock_evt_{next(_ids)}",
                    event_type="invoice.paid",
                    kind="invoice_updated",
                    provider_customer_id=customer_id,
                    invoice=inv,
                )
            )
        return CheckoutSession(url=success_url, events=events)

    async def create_portal(self, *, customer_id: str, return_url: str) -> PortalSession:
        return PortalSession(url=return_url)

    async def create_subscription(self, *, customer_id: str, price_id: str,
                                  trial_days: Optional[int] = None) -> SubscriptionState:
        return self._subscription(customer_id, price_id, trial_days)

    def _get(self, sid: str) -> SubscriptionState:
        state = _subs.get(sid)
        if state is None:
            raise BillingProviderError(f"assinatura desconhecida no mock: {sid}")
        return state

    async def update_subscription(self, provider_subscription_id: str, *,
                                  price_id: str) -> SubscriptionState:
        state = self._get(provider_subscription_id)
        state.provider_price_id = price_id
        return state

    async def cancel_subscription(self, provider_subscription_id: str, *,
                                  at_period_end: bool = True) -> SubscriptionState:
        state = self._get(provider_subscription_id)
        if at_period_end:
            state.cancel_at_period_end = True
        else:
            state.status = "canceled"
            state.canceled_at = _now()
        return state

    async def reactivate_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        state = self._get(provider_subscription_id)
        state.cancel_at_period_end = False
        if state.status == "canceled":
            state.status = "active"
            state.canceled_at = None
        return state

    async def pause_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        state = self._get(provider_subscription_id)
        state.status = "paused"
        state.paused = True
        return state

    async def resume_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        state = self._get(provider_subscription_id)
        state.status = "active"
        state.paused = False
        state.resumes_at = None
        return state

    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        return self._get(provider_subscription_id)

    async def get_invoices(self, customer_id: str, *, limit: int = 24) -> list[InvoiceState]:
        return list(reversed(_invoices.get(customer_id, [])))[:limit]

    async def refund_payment(self, provider_payment_id: str, *, amount=None) -> None:
        return None

    async def sync_plan(self, *, plan_slug: str, plan_name: str, product_id: Optional[str],
                        prices: list[dict]) -> tuple[str, dict[str, str]]:
        pid = product_id or f"mock_prod_{plan_slug}"
        out: dict[str, str] = {}
        for price in prices:
            price_id = price.get("provider_price_id") or f"mock_price_{plan_slug}_{price['cycle']}"
            _prices[price_id] = Decimal(str(price["amount"]))
            out[price["cycle"]] = price_id
        return pid, out

    def parse_webhook(self, *, headers: Mapping[str, str], body: bytes) -> list[ProviderEvent]:
        # Mock opera 100% síncrono (events no checkout) — não há webhook.
        raise BillingProviderError("provider mock não recebe webhooks")
