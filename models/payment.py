"""Financeiro: Payment (realizado), ExpenseCategory, Expense."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import PaymentMethod, pg_enum

if TYPE_CHECKING:
    from .appointment import Appointment
    from .organization import Organization
    from .unit import Unit


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="payments_amount_nonneg"),
        CheckConstraint(
            "tip_amount IS NULL OR tip_amount >= 0", name="payments_tip_nonneg"
        ),
        Index("idx_payments_appt", "appointment_id"),
        Index("idx_payments_org_paid", "organization_id", "paid_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    appointment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("appointments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    tip_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    method: Mapped[PaymentMethod] = mapped_column(
        pg_enum(PaymentMethod, "payment_method"), nullable=False
    )
    paid_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="payments")
    appointment: Mapped["Appointment"] = relationship(back_populates="payments")


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="expense_cat_unique"),
        # idx por organization_id coberto pelo UNIQUE acima (prefixo).
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    organization: Mapped["Organization"] = relationship(
        back_populates="expense_categories"
    )
    expenses: Mapped[List["Expense"]] = relationship(back_populates="category")


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="expenses_amount_nonneg"),
        CheckConstraint(
            "EXTRACT(DAY FROM competence_month) = 1",
            name="expenses_competence_first_day",
        ),
        Index("idx_expenses_org_month", "organization_id", "competence_month"),
        Index("idx_expenses_unit", "unit_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("expense_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    competence_month: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="expenses")
    unit: Mapped["Unit"] = relationship(back_populates="expenses")
    category: Mapped["ExpenseCategory"] = relationship(back_populates="expenses")
