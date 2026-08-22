# file: app/services/connect/provider.py
"""Contrato do gateway de **Connect** (compra online do cliente final).

Deliberadamente NÃO estende `BillingProvider` (`app/services/billing/`): aquele
domínio é a plataforma cobrando a barbearia (assinatura SaaS, conta única da
plataforma); este é a barbearia cobrando o cliente final na **connected account
dela**, com a plataforma retendo uma `application_fee`. Contas, chaves,
segredos de webhook e ciclo de vida são diferentes — misturar as duas
interfaces só criaria acoplamento sem reuso real.

O que se repete do D-61 é o *padrão*: interface fina + implementação Stripe
isolada num único módulo + registry com kill switch + mock determinístico que
deixa a suíte rodar sem chave real.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, runtime_checkable


class ConnectProviderError(Exception):
    """Erro do gateway já traduzido (mensagem segura p/ log; nunca vaza segredo)."""


@runtime_checkable
class ConnectProvider(Protocol):
    """Operações que o domínio precisa de QUALQUER gateway de marketplace."""

    name: str

    # ── onboarding da connected account ─────────────────────────────────────
    async def create_account(self, *, org_id: int, org_name: str,
                             email: Optional[str]) -> str:
        """Cria a conta conectada da barbearia e devolve o id externo."""
        ...

    async def create_account_session(self, account_id: str) -> dict[str, Any]:
        """Sessão efêmera p/ os componentes embutidos (`{client_secret}`)."""
        ...

    async def retrieve_account(self, account_id: str) -> dict[str, Any]:
        """Estado da conta: `charges_enabled`/`payouts_enabled`/`details_submitted`."""
        ...

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
        """Checkout hospedado NA connected account (`{session_id, checkout_url}`)."""
        ...

    # ── webhooks ────────────────────────────────────────────────────────────
    def parse_webhook(self, payload: bytes, sig_header: str) -> Any:
        """Verifica a ASSINATURA e devolve o evento.

        Levanta `ConnectProviderError` em assinatura inválida — o router
        traduz para **400** (nunca 200, nunca 500) e não grava nada.
        """
        ...
