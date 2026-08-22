# file: app/services/connect/stripe_connect_provider.py
"""Implementação Stripe do `ConnectProvider` — ÚNICO módulo que importa `stripe`.

Isolar o SDK aqui é o que permite rodar a suíte inteira sem chave real (o
`registry` devolve o mock) e trocar de gateway sem tocar em regra de negócio.

**Accounts v1 e não v2 (decisão registrada):** o SDK instalado (`stripe`
15.3.0) *expõe* `StripeClient(...).v2.core.accounts`, mas a API v2 de Accounts
depende de habilitação na conta da plataforma e tem forma de payload em
evolução. As *controller properties* da v1 já entregam exatamente o desenho
aprovado no plano e são GA:

- `controller.stripe_dashboard.type="express"` → dashboard Express da barbearia;
- `controller.fees.payer="account"` → a barbearia paga a taxa de processamento;
- `controller.losses.payments="stripe"` → a Stripe assume perdas/chargebacks
  (é o que dispensa a plataforma de fazer KYC/risco).

Migrar para v2 depois é trocar o corpo de `create_account` — nada mais do
sistema conhece a forma da chamada.

Chamadas usam as variantes `*_async` do SDK (o app é async de ponta a ponta).
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

import stripe

from .provider import ConnectProviderError

logger = logging.getLogger(__name__)


class StripeConnectProvider:
    """Direct charges na connected account + `application_fee_amount`."""

    name = "stripe_connect"

    def __init__(self, api_key: str, webhook_secret: str = "") -> None:
        if not api_key:
            raise ConnectProviderError("STRIPE_CONNECT_SECRET_KEY ausente.")
        self._api_key = api_key
        self._webhook_secret = webhook_secret

    # ── onboarding ──────────────────────────────────────────────────────────

    async def create_account(self, *, org_id: int, org_name: str,
                             email: Optional[str]) -> str:
        try:
            account = await stripe.Account.create_async(
                api_key=self._api_key,
                country="BR",
                email=email or None,
                controller={
                    "stripe_dashboard": {"type": "express"},
                    "fees": {"payer": "account"},
                    "losses": {"payments": "stripe"},
                },
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
                business_profile={"name": org_name},
                metadata={"organization_id": str(org_id)},
            )
        except stripe.StripeError as exc:  # pragma: no cover — exige chave real
            raise ConnectProviderError(f"Stripe recusou a criação da conta: {exc}") from exc
        return account.id

    async def create_account_session(self, account_id: str) -> dict[str, Any]:
        try:
            session = await stripe.AccountSession.create_async(
                api_key=self._api_key,
                account=account_id,
                components={
                    "account_onboarding": {"enabled": True},
                    "notification_banner": {"enabled": True},
                    "account_management": {"enabled": True},
                },
            )
        except stripe.StripeError as exc:  # pragma: no cover
            raise ConnectProviderError(f"Stripe recusou a sessão de conta: {exc}") from exc
        return {"client_secret": session.client_secret}

    async def retrieve_account(self, account_id: str) -> dict[str, Any]:
        try:
            account = await stripe.Account.retrieve_async(
                account_id, api_key=self._api_key
            )
        except stripe.StripeError as exc:  # pragma: no cover
            raise ConnectProviderError(f"Stripe não devolveu a conta: {exc}") from exc
        return {
            "id": account.id,
            "charges_enabled": bool(account.get("charges_enabled")),
            "payouts_enabled": bool(account.get("payouts_enabled")),
            "details_submitted": bool(account.get("details_submitted")),
        }

    # ── cobrança ────────────────────────────────────────────────────────────

    async def create_checkout_session(
        self,
        *,
        account_id: str,
        amount_cents: int,
        fee_cents: int,
        currency: str,
        product_name: str,
        client_reference_id: str,
        customer_email: Optional[str],
        metadata: Mapping[str, str],
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        """`stripe_account=` faz a cobrança acontecer NA conta da barbearia
        (direct charge: ela é a merchant of record); `application_fee_amount`
        é a fatia retida pela plataforma, calculada por `resolve_fee_cents`."""
        payment_intent_data: dict[str, Any] = {}
        if fee_cents > 0:
            payment_intent_data["application_fee_amount"] = fee_cents
        try:
            session = await stripe.checkout.Session.create_async(
                api_key=self._api_key,
                stripe_account=account_id,
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": currency,
                            "product_data": {"name": product_name},
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                payment_intent_data=payment_intent_data or None,
                client_reference_id=client_reference_id,
                customer_email=customer_email or None,
                metadata=dict(metadata),
                success_url=success_url,
                cancel_url=cancel_url,
            )
        except stripe.StripeError as exc:  # pragma: no cover
            raise ConnectProviderError(f"Stripe recusou o checkout: {exc}") from exc
        return {"session_id": session.id, "checkout_url": session.url}

    # ── webhooks ────────────────────────────────────────────────────────────

    def parse_webhook(self, payload: bytes, sig_header: str) -> Any:
        if not self._webhook_secret:
            raise ConnectProviderError("STRIPE_CONNECT_WEBHOOK_SECRET ausente.")
        try:
            return stripe.Webhook.construct_event(
                payload, sig_header, self._webhook_secret
            )
        except Exception as exc:  # assinatura/payload inválidos → 400 no router
            raise ConnectProviderError(f"Assinatura de webhook inválida: {exc}") from exc
