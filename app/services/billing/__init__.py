"""Billing do SaaS (superadmin M7) — camada desacoplada de gateway.

Regra de ouro (SA-D04): TODA regra de negócio fala com `BillingProvider`;
`StripeBillingProvider` é o único módulo que importa o SDK da Stripe. Trocar de
gateway = nova classe + `BILLING_PROVIDER` no env, zero mudança de regra.
"""

from .provider import BillingProvider, BillingProviderError
from .registry import get_billing_provider

__all__ = ["BillingProvider", "BillingProviderError", "get_billing_provider"]
