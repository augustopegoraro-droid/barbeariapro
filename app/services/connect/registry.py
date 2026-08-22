# file: app/services/connect/registry.py
"""Factory do provider de Connect — porta única do kill switch.

`CONNECT_ENABLED=False` (default) ou ausência de `STRIPE_CONNECT_SECRET_KEY`
devolvem o mock: o SDK da Stripe nunca é carregado, nenhuma chamada externa
acontece e nada do comportamento atual do sistema muda. Ligar a feature é
mexer no `.env` da VM, não no código.
"""

from __future__ import annotations

from app.core.config import settings

from .provider import ConnectProvider


def connect_is_live() -> bool:
    """True só quando a feature está ligada E há chave configurada."""
    return bool(settings.connect_enabled and settings.stripe_connect_secret_key)


def get_connect_provider() -> ConnectProvider:
    if not connect_is_live():
        from .mock_provider import MockConnectProvider

        return MockConnectProvider()
    # Import tardio: o SDK da Stripe só carrega quando a feature está no ar.
    from .stripe_connect_provider import StripeConnectProvider

    return StripeConnectProvider(
        settings.stripe_connect_secret_key, settings.stripe_connect_webhook_secret
    )
