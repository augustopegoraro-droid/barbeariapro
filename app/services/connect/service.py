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


def estimate_stripe_fee_cents(amount_cents: int) -> int:
    """Estimativa (em centavos) do que a Stripe cobra da connected account
    numa cobrança de cartão nacional: `pct% + fixo` (`STRIPE_DOMESTIC_FEE_PCT`/
    `_FIXED_CENTS`, default 3,99% + R$0,39 — stripe.com/br/pricing).

    Função **pura**, só para dimensionar `application_fee_amount` no momento
    da cobrança — não é o valor real (a Stripe não devolve a taxa antes de
    processar; a taxa efetiva pode variar por bandeira/parcelamento/cartão
    internacional). Arredonda a favor da Stripe (`ROUND_CEILING` na parte
    percentual) para nunca **superestimar** a fatia livre para a comissão —
    o alvo (`resolve_fee_cents`) é um teto, não pode estourar por causa de um
    centavo de estimativa otimista.
    """
    if amount_cents <= 0:
        return 0
    try:
        pct = Decimal(str(settings.stripe_domestic_fee_pct))
    except (InvalidOperation, ValueError):
        logger.warning(
            "STRIPE_DOMESTIC_FEE_PCT inválido (%r) — assumindo 0.",
            settings.stripe_domestic_fee_pct,
        )
        pct = Decimal(0)
    variable = (Decimal(amount_cents) * pct / Decimal(100)).to_integral_value(
        rounding="ROUND_CEILING"
    )
    fixed = max(0, int(settings.stripe_domestic_fee_fixed_cents))
    return min(int(variable) + fixed, amount_cents)


def resolve_fee_cents(org: Organization, amount_cents: int) -> int:
    """Fatia (em centavos) que a PLATAFORMA retém da venda — não o total
    descontado do cliente final (esse é `amount_cents`, cobrado por inteiro).

    `org.platform_fee_pct` (ou o default) é o **percentual total desejado**
    sobre a venda somando taxa da Stripe + comissão da plataforma — decisão de
    negócio: "minha comissão é o que sobra até bater X% no total", não um
    percentual isolado. A fórmula é:

        comissão = (alvo% × valor) − taxa_stripe_estimada(valor)

    Função **pura** e testável isoladamente. Regras:
    - `org.platform_fee_pct` manda; NULL cai no `PLATFORM_FEE_PCT_DEFAULT`;
    - a parte alvo trunca para baixo (`floor`) — nunca cobra um centavo a mais
      do que o % pedido; a taxa da Stripe é estimada à parte (arredondada a
      favor da Stripe, ver `estimate_stripe_fee_cents`) e subtraída;
    - clamp `0 <= fee <= amount_cents`: quando a taxa estimada da Stripe já
      consome o alvo inteiro (típico em valores baixos, onde o R$0,39 fixo
      pesa mais), a comissão da plataforma cai para 0 — nunca fica negativa
      nem engole a venda inteira (a Stripe recusaria, e a CHECK da 0062
      também).
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
    target = int((Decimal(amount_cents) * Decimal(pct) / Decimal(100)).to_integral_value(
        rounding="ROUND_FLOOR"
    ))
    fee = target - estimate_stripe_fee_cents(amount_cents)
    return max(0, min(fee, amount_cents))
