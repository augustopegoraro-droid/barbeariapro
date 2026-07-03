"""Profissionais: Barber, BarberUnit (atuação N:N), TimeOff."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    Text,
    TIMESTAMP,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .appointment import AppointmentItem
    from .organization import Organization
    from .service import Service
    from .unit import Unit
    from .user import UserUnit


class Barber(Base):
    __tablename__ = "barbers"
    __table_args__ = (
        CheckConstraint(
            "commission_pct >= 0 AND commission_pct <= 1",
            name="barbers_commission_range",
        ),
        CheckConstraint(
            "work_model IS NULL OR work_model IN "
            "('clt', 'mei', 'comissionado', 'aluguel_cadeira', 'hibrido')",
            name="barbers_work_model_valid",
        ),
        # Dinheiro nunca negativo (migration 0027) — protege o cálculo de folha/
        # cobertura contra writers fora da API. Mesma defesa do commission_range.
        CheckConstraint("monthly_cost >= 0", name="barbers_monthly_cost_nonneg"),
        CheckConstraint("chair_rent >= 0", name="barbers_chair_rent_nonneg"),
        Index("idx_barbers_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    specialty: Mapped[Optional[str]] = mapped_column(Text)
    commission_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("0")
    )
    # Gestão de equipe (migration 0025): modelo de trabalho + custos mensais.
    # work_model NULL = não configurado (tratado como 'comissionado').
    work_model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    monthly_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    chair_rent: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="barbers")
    unit_links: Mapped[List["BarberUnit"]] = relationship(back_populates="barber")
    user_links: Mapped[List["UserUnit"]] = relationship(back_populates="barber")
    time_off: Mapped[List["TimeOff"]] = relationship(back_populates="barber")
    appointment_items: Mapped[List["AppointmentItem"]] = relationship(
        back_populates="barber"
    )
    service_links: Mapped[List["BarberService"]] = relationship(
        back_populates="barber", cascade="all, delete-orphan"
    )


class BarberUnit(Base):
    __tablename__ = "barber_units"
    __table_args__ = (Index("idx_barber_units_unit", "unit_id"),)

    barber_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("barbers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("units.id", ondelete="CASCADE"),
        primary_key=True,
    )

    barber: Mapped["Barber"] = relationship(back_populates="unit_links")
    unit: Mapped["Unit"] = relationship(back_populates="barber_links")


class TimeOff(Base):
    __tablename__ = "time_off"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="time_off_valid"),
        Index("idx_time_off_barber", "barber_id", "start_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)

    barber: Mapped["Barber"] = relationship(back_populates="time_off")


class BarberService(Base):
    """Vínculo N:N entre profissional e serviço que ele executa."""

    __tablename__ = "barber_services"
    __table_args__ = (Index("idx_barber_services_service", "service_id"),)

    barber_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("barbers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    service_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("services.id", ondelete="CASCADE"),
        primary_key=True,
    )

    barber: Mapped["Barber"] = relationship(back_populates="service_links")
    service: Mapped["Service"] = relationship(back_populates="barber_links")
