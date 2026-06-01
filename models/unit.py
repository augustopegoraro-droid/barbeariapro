"""Estrutura física: Unit, BusinessHours."""

from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    Time,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .appointment import Appointment
    from .barber import BarberUnit
    from .integration import IntegrationAccount
    from .organization import Organization
    from .payment import Expense
    from .user import UserUnit


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (Index("idx_units_org", "organization_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'America/Sao_Paulo'")
    )
    address: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="units")
    business_hours: Mapped[List["BusinessHours"]] = relationship(
        back_populates="unit"
    )
    appointments: Mapped[List["Appointment"]] = relationship(back_populates="unit")
    expenses: Mapped[List["Expense"]] = relationship(back_populates="unit")
    user_links: Mapped[List["UserUnit"]] = relationship(back_populates="unit")
    barber_links: Mapped[List["BarberUnit"]] = relationship(back_populates="unit")
    integration_accounts: Mapped[List["IntegrationAccount"]] = relationship(
        back_populates="unit"
    )


class BusinessHours(Base):
    __tablename__ = "business_hours"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="bh_weekday_range"),
        CheckConstraint("close_time > open_time", name="bh_time_valid"),
        UniqueConstraint("unit_id", "weekday", "open_time", name="bh_unique_slot"),
        Index("idx_business_hours_unit", "unit_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=dom ... 6=sáb
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)

    unit: Mapped["Unit"] = relationship(back_populates="business_hours")
