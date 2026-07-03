"""Billing do SaaS (migration 0032) — faturas, pagamentos, cupons, créditos.

DISTINÇÃO IMPORTANTE: aqui é o dinheiro TENANT → PLATAFORMA. O dinheiro do
cliente final (comandas/mensalidades da barbearia) vive em `payment.py`/
`membership.py`. Por isso `billing_payments` (e não `payments`).

Acesso (decisões SA-D03):
- Catálogos globais (`plan_prices`, `feature_flags`, `plan_features`,
  `plan_limits`, `coupons`): sem RLS, molde de `plans`.
- Tabelas por org (`billing_customers`, `invoices`, `billing_payments`,
  `payment_attempts`, `discounts`, `billing_credits`, `usage_metrics`,
  `billing_events`): RLS `tenant_isolation` — o tenant lê as próprias em
  "Minha assinatura"; a plataforma lê cross-org via funções SECURITY DEFINER e
  escreve via sessões helper escopadas (molde D-55).
- `webhook_events`: recebida ANTES de resolver a org (idempotência por
  `(provider, event_id)`); sem RLS, nunca exposta a rotas de tenant.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PlanPrice(Base):
    """Preço de um plano por ciclo (mensal/anual), espelhável no gateway."""

    __tablename__ = "plan_prices"
    __table_args__ = (
        CheckConstraint("cycle IN ('monthly', 'yearly')", name="plan_prices_cycle_valid"),
        CheckConstraint("amount >= 0", name="plan_prices_amount_nonneg"),
        UniqueConstraint("plan_id", "cycle", name="plan_prices_plan_cycle_unique"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    cycle: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'brl'"))
    provider_price_id: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class FeatureFlag(Base):
    """Registro global de recursos do produto (gerenciável no superadmin)."""

    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    default_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class PlanFeature(Base):
    """Recurso habilitado (ou não) num plano."""

    __tablename__ = "plan_features"

    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    feature_key: Mapped[str] = mapped_column(
        Text, ForeignKey("feature_flags.key", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


class PlanLimit(Base):
    """Limite numérico de um plano (`value` NULL = ilimitado)."""

    __tablename__ = "plan_limits"
    __table_args__ = (
        CheckConstraint("value IS NULL OR value >= 0", name="plan_limits_value_nonneg"),
    )

    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    limit_key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[int]] = mapped_column(Integer)


class BillingCustomer(Base):
    """Mapa org ↔ customer no gateway (resolução de webhooks)."""

    __tablename__ = "billing_customers"
    __table_args__ = (
        UniqueConstraint("provider", "provider_customer_id", name="billing_customers_provider_cid_unique"),
        UniqueConstraint("provider", "organization_id", name="billing_customers_provider_org_unique"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Invoice(Base):
    """Fatura do SaaS (tenant → plataforma)."""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'open', 'paid', 'void', 'uncollectible')",
            name="invoices_status_valid",
        ),
        CheckConstraint("amount_due >= 0", name="invoices_amount_due_nonneg"),
        CheckConstraint("amount_paid >= 0", name="invoices_amount_paid_nonneg"),
        Index("idx_invoices_org", "organization_id"),
        Index("idx_invoices_status", "status"),
        UniqueConstraint("provider", "provider_invoice_id", name="invoices_provider_iid_unique"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    provider_invoice_id: Mapped[Optional[str]] = mapped_column(Text)
    number: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    amount_due: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'brl'"))
    period_start: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    period_end: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    due_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    paid_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    hosted_invoice_url: Mapped[Optional[str]] = mapped_column(Text)
    pdf_url: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class BillingPayment(Base):
    """Pagamento de fatura do SaaS (nome distinto do `payments` do cliente final)."""

    __tablename__ = "billing_payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded', 'partially_refunded')",
            name="billing_payments_status_valid",
        ),
        CheckConstraint("amount >= 0", name="billing_payments_amount_nonneg"),
        Index("idx_billing_payments_org", "organization_id"),
        UniqueConstraint("provider", "provider_payment_id", name="billing_payments_provider_pid_unique"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    provider_payment_id: Mapped[Optional[str]] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'brl'"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[Optional[str]] = mapped_column(Text)
    failure_code: Mapped[Optional[str]] = mapped_column(Text)
    failure_message: Mapped[Optional[str]] = mapped_column(Text)
    paid_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    refunded_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class PaymentAttempt(Base):
    """Tentativa de cobrança de uma fatura (registro do dunning do gateway)."""

    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="payment_attempts_number_positive"),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="payment_attempts_status_valid",
        ),
        UniqueConstraint("invoice_id", "attempt_number", name="payment_attempts_invoice_n_unique"),
        Index("idx_payment_attempts_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    provider_error_code: Mapped[Optional[str]] = mapped_column(Text)
    provider_error_message: Mapped[Optional[str]] = mapped_column(Text)
    attempted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Coupon(Base):
    """Cupom do SaaS (catálogo global; espelhado no gateway quando suportado)."""

    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint(
            "(percent_off IS NOT NULL) <> (amount_off IS NOT NULL)",
            name="coupons_percent_xor_amount",
        ),
        CheckConstraint(
            "percent_off IS NULL OR (percent_off > 0 AND percent_off <= 100)",
            name="coupons_percent_range",
        ),
        CheckConstraint("amount_off IS NULL OR amount_off > 0", name="coupons_amount_positive"),
        CheckConstraint(
            "duration IN ('once', 'repeating', 'forever')", name="coupons_duration_valid"
        ),
        CheckConstraint(
            "duration <> 'repeating' OR duration_months > 0",
            name="coupons_repeating_months",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    percent_off: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    amount_off: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'brl'"))
    duration: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'once'"))
    duration_months: Mapped[Optional[int]] = mapped_column(Integer)
    max_redemptions: Mapped[Optional[int]] = mapped_column(Integer)
    times_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    valid_until: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    provider_coupon_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Discount(Base):
    """Aplicação de um cupom/desconto a uma org (auditável)."""

    __tablename__ = "discounts"
    __table_args__ = (Index("idx_discounts_org", "organization_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    coupon_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("coupons.id", ondelete="RESTRICT"), nullable=False
    )
    provider_discount_id: Mapped[Optional[str]] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    ends_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("platform_admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class BillingCredit(Base):
    """Ledger append-only de créditos (+ concede, − consome). Saldo = SUM."""

    __tablename__ = "billing_credits"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="billing_credits_amount_nonzero"),
        CheckConstraint(
            "source IN ('admin', 'refund', 'promo', 'consumption')",
            name="billing_credits_source_valid",
        ),
        Index("idx_billing_credits_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'brl'"))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("platform_admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class UsageMetric(Base):
    """Contador mensal por org/métrica (enforcement de limites + analytics)."""

    __tablename__ = "usage_metrics"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "metric_key", "period", name="usage_metrics_org_key_period_unique"
        ),
        CheckConstraint("value >= 0", name="usage_metrics_value_nonneg"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)  # 1º dia do mês
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class BillingEvent(Base):
    """Log append-only de tudo que muda billing (histórico + auditoria)."""

    __tablename__ = "billing_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('system', 'platform_admin', 'tenant', 'provider')",
            name="billing_events_actor_valid",
        ),
        Index("idx_billing_events_org", "organization_id"),
        Index("idx_billing_events_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    actor_label: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class WebhookEvent(Base):
    """Evento bruto recebido do gateway — idempotência, auditoria e replay."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="webhook_events_provider_eid_unique"),
        CheckConstraint(
            "status IN ('received', 'processed', 'failed', 'skipped')",
            name="webhook_events_status_valid",
        ),
        Index("idx_webhook_events_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    organization_id: Mapped[Optional[int]] = mapped_column(BigInteger)  # resolvida no processamento
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'received'"))
    error: Mapped[Optional[str]] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
