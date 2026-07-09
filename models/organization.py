"""SaaS / Tenant: Plan, Organization, Subscription."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    TIMESTAMP,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import SubscriptionStatus, pg_enum

if TYPE_CHECKING:
    from .barber import Barber
    from .client import Client
    from .appointment import Appointment
    from .integration import IntegrationAccount, MessageLog
    from .payment import Expense, ExpenseCategory, Payment
    from .service import Service
    from .unit import Unit
    from .user import User


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("price_month >= 0", name="plans_price_nonneg"),
        CheckConstraint("max_units > 0", name="plans_units_positive"),
        CheckConstraint("max_barbers > 0", name="plans_barbers_pos"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    price_month: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    max_units: Mapped[int] = mapped_column(Integer, nullable=False)
    max_barbers: Mapped[int] = mapped_column(Integer, nullable=False)
    # Congelado (nunca foi lido por código) — substituído por plan_features/
    # plan_limits normalizados na migration 0032. Mantido por retrocompat.
    features: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, server_default=text("'{}'::jsonb")
    )
    # Billing SaaS (migration 0032). slug estável p/ código/integrações;
    # stripe_product_id espelha o Product na Stripe (nullable até sincronizar).
    slug: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    stripe_product_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    subscriptions: Mapped[List["Subscription"]] = relationship(back_populates="plan")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, unique=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Resolução de tenant (multi-tenant real, migration 0020). Ambos NULL p/ orgs
    # antigas; únicos quando não-nulos (índices parciais).
    # - subdomain: slug do login (taylor.app.com → org); substitui NEXT_PUBLIC_ORG_ID.
    # - wa_instance_name: instância Evolution que recebe os webhooks da barbearia;
    #   o bot resolve a org pela instância do payload.
    subdomain: Mapped[Optional[str]] = mapped_column(Text)
    wa_instance_name: Mapped[Optional[str]] = mapped_column(Text)
    # Dados cadastrais (tela /admin/empresa). Todos opcionais — retrocompat.
    legal_name: Mapped[Optional[str]] = mapped_column(Text)
    cnpj: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text)
    website: Mapped[Optional[str]] = mapped_column(Text)
    instagram: Mapped[Optional[str]] = mapped_column(Text)
    logo_url: Mapped[Optional[str]] = mapped_column(Text)
    # Meta de faturamento mensal (R$); NULL = sem meta. Usada no alerta proativo.
    monthly_revenue_goal: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    # Retenção da auditoria (meses), configurável por org (Fase 4, D-70).
    audit_retention_months: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("12")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    subscriptions: Mapped[List["Subscription"]] = relationship(
        back_populates="organization"
    )
    units: Mapped[List["Unit"]] = relationship(back_populates="organization")
    users: Mapped[List["User"]] = relationship(back_populates="organization")
    barbers: Mapped[List["Barber"]] = relationship(back_populates="organization")
    services: Mapped[List["Service"]] = relationship(back_populates="organization")
    clients: Mapped[List["Client"]] = relationship(back_populates="organization")
    appointments: Mapped[List["Appointment"]] = relationship(
        back_populates="organization"
    )
    payments: Mapped[List["Payment"]] = relationship(back_populates="organization")
    expense_categories: Mapped[List["ExpenseCategory"]] = relationship(
        back_populates="organization"
    )
    expenses: Mapped[List["Expense"]] = relationship(back_populates="organization")
    integration_accounts: Mapped[List["IntegrationAccount"]] = relationship(
        back_populates="organization"
    )
    messages: Mapped[List["MessageLog"]] = relationship(back_populates="organization")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "current_period_end > current_period_start", name="subs_period_valid"
        ),
        Index("idx_subscriptions_org", "organization_id"),
        Index("idx_subscriptions_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        pg_enum(SubscriptionStatus, "subscription_status"),
        nullable=False,
        server_default=text("'trial'"),
    )
    current_period_start: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    canceled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    # Billing SaaS (migration 0032). provider 'manual' = sem gateway (estado
    # gerido pelo lifecycle job); 'stripe' = estado dirigido por webhooks.
    provider: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'manual'")
    )
    provider_customer_id: Mapped[Optional[str]] = mapped_column(Text)
    provider_subscription_id: Mapped[Optional[str]] = mapped_column(Text)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    trial_end: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    paused_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    resumes_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")
