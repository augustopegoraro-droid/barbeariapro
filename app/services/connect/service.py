# file: app/services/connect/service.py
"""Regra de negócio do Stripe Connect (único chamador do provider).

Fica fora do router de propósito, no molde de `app/services/billing/service.py`
e de `management.py`: as funções são reaproveitáveis por rota de tenant,
webhook e cron sem duplicar lógica.

A invalidação de cache do site público NÃO é disparada aqui — `sync_account_status`
apenas *informa* se `charges_enabled` mudou, e quem chama registra
`invalidate_public_tags` em `BackgroundTasks` (roda após o commit, e falha nela
nunca derruba a escrita — regra do D-84).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from models import Organization

from .provider import ConnectProviderError
from .registry import get_connect_provider

logger = logging.getLogger(__name__)


async def ensure_account(db: AsyncSession, org: Organization) -> str:
    """Id da connected account da org, criando-a se ainda não existir.

    Idempotente: com a conta já persistida, nem toca no provider — clicar duas
    vezes em "Ativar recebimentos" não abre duas contas na Stripe (e o índice
    UNIQUE parcial da 0062 é o backstop no banco).
    """
    if org.stripe_connected_account_id:
        return org.stripe_connected_account_id

    provider = get_connect_provider()
    account_id = await provider.create_account(
        org_id=org.id, org_name=org.name, email=org.email
    )
    org.stripe_connected_account_id = account_id
    await db.flush()
    return account_id


async def account_session(db: AsyncSession, org: Organization) -> dict:
    """`client_secret` efêmero p/ os componentes embutidos do painel."""
    if not org.stripe_connected_account_id:
        raise ConnectProviderError("Organização ainda não tem conta conectada.")
    provider = get_connect_provider()
    return await provider.create_account_session(org.stripe_connected_account_id)


async def sync_account_status(db: AsyncSession, org: Organization) -> bool:
    """Copia os flags de capacidade da Stripe para a org.

    Retorna **True quando `charges_enabled` mudou** — é o sinal de que a
    vitrine pública precisa ser invalidada (o gate de venda depende dele).
    """
    if not org.stripe_connected_account_id:
        raise ConnectProviderError("Organização ainda não tem conta conectada.")

    provider = get_connect_provider()
    data = await provider.retrieve_account(org.stripe_connected_account_id)
    return apply_account_flags(org, data)


def apply_account_flags(org: Organization, data: dict) -> bool:
    """Aplica os 3 flags + carimbo de sync. Função pura sobre o objeto ORM —
    o webhook `account.updated` reaproveita com o payload que já recebeu,
    sem uma segunda ida à Stripe."""
    before = org.stripe_connect_charges_enabled
    org.stripe_connect_charges_enabled = bool(data.get("charges_enabled"))
    org.stripe_connect_payouts_enabled = bool(data.get("payouts_enabled"))
    org.stripe_connect_details_submitted = bool(data.get("details_submitted"))
    org.stripe_connect_synced_at = datetime.now(timezone.utc)
    return before != org.stripe_connect_charges_enabled


def resolve_fee_cents(org: Organization, amount_cents: int) -> int:
    """Fatia (em centavos) que a plataforma retém da venda.

    Função **pura** e testável isoladamente. Regras:
    - `org.platform_fee_pct` manda; NULL cai no `PLATFORM_FEE_PCT_DEFAULT`;
    - trunca para baixo (`floor`) — nunca cobra um centavo a mais do que a %;
    - clamp `0 <= fee <= amount_cents`: a taxa jamais é negativa nem engole a
      venda inteira (a Stripe recusaria, e a CHECK da 0062 também).
    """
    if amount_cents <= 0:
        return 0
    pct = org.platform_fee_pct
    if pct is None:
        try:
            pct = Decimal(str(settings.platform_fee_pct_default))
        except (InvalidOperation, ValueError):
            logger.warning(
                "PLATFORM_FEE_PCT_DEFAULT inválido (%r) — assumindo 0.",
                settings.platform_fee_pct_default,
            )
            pct = Decimal(0)
    if pct <= 0:
        return 0
    fee = int((Decimal(amount_cents) * Decimal(pct) / Decimal(100)).to_integral_value(
        rounding="ROUND_FLOOR"
    ))
    return max(0, min(fee, amount_cents))
