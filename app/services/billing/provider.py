"""Interface `BillingProvider` — contrato único de gateway (SA-D04)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Mapping, Optional

from .types import (
    CheckoutSession,
    InvoiceState,
    PortalSession,
    ProviderEvent,
    SubscriptionState,
)


class BillingProviderError(Exception):
    """Erro de gateway traduzido (mensagem segura p/ log; nunca vaza segredo)."""


class BillingProvider(ABC):
    """Operações que o domínio precisa de QUALQUER gateway de pagamento.

    Implementações: StripeBillingProvider (produção), MockBillingProvider
    (dev/testes). Futuras: Asaas, MercadoPago — mesma interface, só config.
    """

    name: str

    # ── clientes ─────────────────────────────────────────────────────────────
    @abstractmethod
    async def create_customer(self, *, org_id: int, name: str, email: Optional[str]) -> str:
        """Cria o customer no gateway e devolve o id externo."""

    @abstractmethod
    async def update_customer(self, customer_id: str, *, name: Optional[str] = None,
                              email: Optional[str] = None) -> None: ...

    # ── ciclo de vida de assinatura ─────────────────────────────────────────
    @abstractmethod
    async def create_checkout(self, *, customer_id: str, price_id: str,
                              success_url: str, cancel_url: str,
                              trial_days: Optional[int] = None) -> CheckoutSession:
        """Checkout hospedado p/ INICIAR assinatura (Stripe: mode=subscription)."""

    @abstractmethod
    async def create_portal(self, *, customer_id: str, return_url: str) -> PortalSession:
        """Portal de autosserviço (trocar cartão, upgrade/downgrade, cancelar)."""

    @abstractmethod
    async def create_subscription(self, *, customer_id: str, price_id: str,
                                  trial_days: Optional[int] = None) -> SubscriptionState:
        """Assinatura criada direto (sem checkout) — uso administrativo."""

    @abstractmethod
    async def update_subscription(self, provider_subscription_id: str, *,
                                  price_id: str) -> SubscriptionState:
        """Up/downgrade de plano (proration a cargo do gateway)."""

    @abstractmethod
    async def cancel_subscription(self, provider_subscription_id: str, *,
                                  at_period_end: bool = True) -> SubscriptionState: ...

    @abstractmethod
    async def reactivate_subscription(self, provider_subscription_id: str) -> SubscriptionState:
        """Desfaz cancel_at_period_end antes do fim do período."""

    @abstractmethod
    async def pause_subscription(self, provider_subscription_id: str) -> SubscriptionState: ...

    @abstractmethod
    async def resume_subscription(self, provider_subscription_id: str) -> SubscriptionState: ...

    # ── leitura / reconciliação ─────────────────────────────────────────────
    @abstractmethod
    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionState: ...

    @abstractmethod
    async def get_invoices(self, customer_id: str, *, limit: int = 24) -> list[InvoiceState]: ...

    @abstractmethod
    async def refund_payment(self, provider_payment_id: str, *,
                             amount: Optional[Decimal] = None) -> None: ...

    # ── catálogo ─────────────────────────────────────────────────────────────
    @abstractmethod
    async def sync_plan(self, *, plan_slug: str, plan_name: str,
                        product_id: Optional[str],
                        prices: list[dict]) -> tuple[str, dict[str, str]]:
        """Espelha o plano (Product) e os preços (Prices) no gateway.

        `prices`: [{cycle, amount, currency, provider_price_id?}].
        Retorna (product_id, {cycle: price_id}).
        """

    # ── webhooks ─────────────────────────────────────────────────────────────
    @abstractmethod
    def parse_webhook(self, *, headers: Mapping[str, str], body: bytes) -> list[ProviderEvent]:
        """Verifica a ASSINATURA do webhook e normaliza os eventos.

        Levanta BillingProviderError em assinatura inválida (→ 400, nunca 200).
        """

    def parse_payload(self, payload: dict) -> ProviderEvent:
        """Normaliza um payload BRUTO já persistido (reprocesso — sem assinatura,
        pois ela foi verificada na recepção original)."""
        raise BillingProviderError(f"provider {self.name} não suporta reprocesso")
