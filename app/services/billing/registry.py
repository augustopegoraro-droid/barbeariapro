"""Factory de provider por configuração (`BILLING_PROVIDER`) — SA-D04."""

from __future__ import annotations

from app.core.config import settings

from .provider import BillingProvider, BillingProviderError


def get_billing_provider(name: str | None = None) -> BillingProvider:
    """Resolve o gateway ativo. Import tardio: o SDK da Stripe só carrega se usado."""
    provider = (name or settings.billing_provider or "mock").strip().lower()
    if provider == "mock":
        from .mock_provider import MockBillingProvider

        return MockBillingProvider()
    if provider == "stripe":
        from .stripe_provider import StripeBillingProvider

        return StripeBillingProvider()
    raise BillingProviderError(f"BILLING_PROVIDER desconhecido: {provider}")
