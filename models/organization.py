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
    features: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, server_default=text("'{}'::jsonb")
    )
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
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")
