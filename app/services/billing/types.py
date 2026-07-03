"""Contratos NORMALIZADOS entre providers e o domínio (agnósticos de gateway).

O provider traduz o vocabulário do gateway para estes tipos; o service só
conhece estes tipos. Status de assinatura usa o enum interno
(`subscription_status`): trial|active|past_due|canceled|paused|incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class SubscriptionState:
    provider_subscription_id: str
    status: str  # enum interno
    provider_customer_id: Optional[str] = None
    provider_price_id: Optional[str] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    trial_end: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    paused: bool = False
    resumes_at: Optional[datetime] = None


@dataclass
class InvoiceState:
    provider_invoice_id: str
    status: str  # draft|open|paid|void|uncollectible
    amount_due: Decimal
    amount_paid: Decimal
    currency: str = "brl"
    number: Optional[str] = None
    provider_customer_id: Optional[str] = None
    provider_subscription_id: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    due_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    hosted_invoice_url: Optional[str] = None
    pdf_url: Optional[str] = None
    # Dunning do gateway (Smart Retries): nº da tentativa e próximo retry.
    attempt_count: Optional[int] = None
    next_retry_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None


@dataclass
class PaymentState:
    provider_payment_id: str
    status: str  # pending|succeeded|failed|refunded|partially_refunded
    amount: Decimal
    currency: str = "brl"
    method: Optional[str] = None
    provider_invoice_id: Optional[str] = None
    provider_customer_id: Optional[str] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    paid_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None


@dataclass
class ProviderEvent:
    """Evento normalizado vindo do gateway (webhook ou fluxo síncrono do mock)."""

    provider: str
    event_id: str
    event_type: str  # tipo cru do gateway (auditoria)
    kind: str  # subscription_updated | invoice_updated | payment_updated | ignored
    provider_customer_id: Optional[str] = None
    subscription: Optional[SubscriptionState] = None
    invoice: Optional[InvoiceState] = None
    payment: Optional[PaymentState] = None


@dataclass
class CheckoutSession:
    url: str
    # Mock: eventos síncronos que o service aplica na hora (simula o webhook).
    events: list[ProviderEvent] = field(default_factory=list)


@dataclass
class PortalSession:
    url: str
