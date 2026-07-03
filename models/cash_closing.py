"""Fechamento de caixa diário (histórico migrado da Trinks; migration 0026)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization


class CashDailyClosing(Base):
    __tablename__ = "cash_daily_closings"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "closing_date", name="cash_daily_closings_org_date_unique"
        ),
        Index("idx_cash_daily_closings_org_date", "organization_id", "closing_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    closing_date: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cash_received: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    change_given: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cash_expenses: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cash_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    withdrawal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    other_methods_received: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    other_methods_expenses: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    opening_history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'trinks'"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
