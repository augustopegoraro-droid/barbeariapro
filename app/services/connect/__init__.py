# file: app/services/connect/__init__.py
"""Stripe Connect — a barbearia cobra o cliente final na conta dela.

Pacote irmão de `app/services/billing/` (onde a PLATAFORMA cobra a barbearia).
Ver `provider.py` para o porquê de os dois contratos não se fundirem.
"""

from .provider import ConnectProvider, ConnectProviderError
from .registry import connect_is_live, get_connect_provider

__all__ = [
    "ConnectProvider",
    "ConnectProviderError",
    "connect_is_live",
    "get_connect_provider",
]
