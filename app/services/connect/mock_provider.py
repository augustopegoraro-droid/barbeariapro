# file: app/services/connect/mock_provider.py
"""Provider de Connect determinístico — dev, staging e SUÍTE DE TESTES.

É o que o `registry` devolve enquanto `CONNECT_ENABLED=False` (default) ou sem
`STRIPE_CONNECT_SECRET_KEY`. Não faz rede, não precisa de chave e responde de
forma previsível, o que permite exercitar o fluxo inteiro (conta → checkout →
webhook → assinatura criada) sem depender da Stripe.

`charges_enabled=True` sempre: o mock representa uma conta com KYC concluído —
o *gate* de negócio (org sem `charges_enabled` não vende) é testado gravando o
flag direto no banco, não simulando um KYC pendente aqui.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping, Optional

from .provider import ConnectProviderError

# Assinatura aceita pelo mock. Constante e óbvia: nada aqui é segredo — o
# provider real (`StripeConnectProvider`) é quem faz verificação criptográfica.
MOCK_SIGNATURE = "mock-signature"


class MockConnectProvider:
    name = "mock_connect"

    async def create_account(self, *, org_id: int, org_name: str,
                             email: Optional[str]) -> str:
        # Determinístico por org: recriar sem persistir devolveria o mesmo id,
        # o que torna óbvia qualquer quebra de idempotência em `ensure_account`.
        return f"acct_mock_{org_id}"

    async def create_account_session(self, account_id: str) -> dict[str, Any]:
        return {"client_secret": f"acs_secret_mock_{account_id}"}

    async def retrieve_account(self, account_id: str) -> dict[str, Any]:
        return {
            "id": account_id,
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
        }

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
        session_id = f"cs_mock_{uuid.uuid4().hex}"
        return {
            "session_id": session_id,
            "checkout_url": f"https://checkout.mock.local/{session_id}",
        }

    def parse_webhook(self, payload: bytes, sig_header: str) -> Any:
        """Aceita só a assinatura conhecida — o caminho "assinatura inválida →
        400, nada gravado" precisa ser testável sem chave real."""
        if sig_header != MOCK_SIGNATURE:
            raise ConnectProviderError("Assinatura de webhook inválida (mock).")
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise ConnectProviderError(f"Payload inválido: {exc}") from exc
