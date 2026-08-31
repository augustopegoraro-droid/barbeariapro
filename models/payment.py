"""Financeiro: Payment (realizado), ExpenseCategory, Expense."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import ExpenseMethod, ExpenseStatus, PaymentMethod, pg_enum

# Slugs de subgrupo compartilhados com `dre_monthly_lines.subgroup` (D-65).
_SUBGROUP_SQL = (
    "{col} IS NULL OR {col} IN ('fixa','variavel','pessoal','impostos','outros')"
)

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
        CheckConstraint(_SUBGROUP_SQL.format(col="subgroup"), name="expenses_subgroup_valid"),
        Index("idx_expenses_org_month", "organization_id", "competence_month"),
        Index("idx_expenses_unit", "unit_id"),
        # Aba "A pagar" (contas em aberto ordenadas por vencimento).
        Index("idx_expenses_status_due", "organization_id", "status", "due_date"),
        # Idempotência do cron de recorrências: 1 conta por template por mês.
        Index(
            "expenses_recurrence_month_unique",
            "organization_id",
            "recurrence_id",
            "competence_month",
            unique=True,
            postgresql_where=text("recurrence_id IS NOT NULL"),
        ),
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
    # ── D-102: despesa rica + contas a pagar + recorrência ───────────────────
    method: Mapped[Optional[ExpenseMethod]] = mapped_column(
        pg_enum(ExpenseMethod, "expense_method")
    )
    subgroup: Mapped[Optional[str]] = mapped_column(Text)
    payee: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[ExpenseStatus] = mapped_column(
        pg_enum(ExpenseStatus, "expense_status"),
        nullable=False,
        server_default="pago",
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    paid_at: Mapped[Optional[date]] = mapped_column(Date)
    recurrence_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("expense_recurrences.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="expenses")
    unit: Mapped["Unit"] = relationship(back_populates="expenses")
    category: Mapped["ExpenseCategory"] = relationship(back_populates="expenses")
    recurrence: Mapped[Optional["ExpenseRecurrence"]] = relationship()


class ExpenseRecurrence(Base):
    """Template de despesa fixa/recorrente (D-102).

    O cron mensal (`POST /internal/expenses/run`) materializa cada recorrência
    ativa numa conta `a_pagar` do mês corrente — idempotente pelo índice único
    parcial `expenses_recurrence_month_unique`. Sem DELETE (GRANT); desativar
    via `active`. Molde de `commission_transfers`/0050.
    """

    __tablename__ = "expense_recurrences"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="expense_recurrences_amount_nonneg"),
        CheckConstraint(
            "day_of_month BETWEEN 1 AND 28", name="expense_recurrences_day_range"
        ),
        CheckConstraint(
            _SUBGROUP_SQL.format(col="subgroup"),
            name="expense_recurrences_subgroup_valid",
        ),
        Index("idx_expense_recurrences_org_active", "organization_id", "active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("expense_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[Optional[ExpenseMethod]] = mapped_column(
        pg_enum(ExpenseMethod, "expense_method")
    )
    subgroup: Mapped[Optional[str]] = mapped_column(Text)
    payee: Mapped[Optional[str]] = mapped_column(Text)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    unit: Mapped["Unit"] = relationship()
    category: Mapped["ExpenseCategory"] = relationship()
