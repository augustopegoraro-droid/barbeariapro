"""Agenda (fato central): Appointment e AppointmentItem (linhas com snapshot)."""

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
    SmallInteger,
    TIMESTAMP,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import AppointmentStatus, ContactChannel, pg_enum

if TYPE_CHECKING:
    from .barber import Barber
    from .client import Client
    from .integration import CalendarSync, MessageLog
    from .organization import Organization
    from .payment import Payment
    from .service import Service
    from .unit import Unit
    from .user import User


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="appt_time_valid"),
        CheckConstraint(
            "rating IS NULL OR (rating BETWEEN 1 AND 5)", name="appt_rating_range"
        ),
        CheckConstraint("total_amount >= 0", name="appt_total_nonneg"),
        UniqueConstraint("unit_id", "display_number", name="appt_display_per_unit"),
        Index("idx_appt_org_start", "organization_id", "start_at"),
        Index("idx_appt_unit_start", "unit_id", "start_at"),
        Index("idx_appt_client_start", "client_id", "start_at"),
        Index("idx_appt_unit_status_start", "unit_id", "status", "start_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, unique=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    display_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        pg_enum(AppointmentStatus, "appointment_status"),
        nullable=False,
        server_default=text("'agendado'"),
    )
    booking_channel: Mapped[Optional[ContactChannel]] = mapped_column(
        pg_enum(ContactChannel, "contact_channel")
    )
    rating: Mapped[Optional[int]] = mapped_column(SmallInteger)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="appointments")
    unit: Mapped["Unit"] = relationship(back_populates="appointments")
    client: Mapped["Client"] = relationship(back_populates="appointments")
    created_by: Mapped[Optional["User"]] = relationship(
        back_populates="created_appointments"
    )
    items: Mapped[List["AppointmentItem"]] = relationship(
        back_populates="appointment", cascade="all, delete-orphan"
    )
    payments: Mapped[List["Payment"]] = relationship(back_populates="appointment")
    calendar_syncs: Mapped[List["CalendarSync"]] = relationship(
        back_populates="appointment", cascade="all, delete-orphan"
    )
    messages: Mapped[List["MessageLog"]] = relationship(back_populates="appointment")


class AppointmentItem(Base):
    __tablename__ = "appointment_items"
    __table_args__ = (
        CheckConstraint("price_charged >= 0", name="appt_items_price_nonneg"),
        CheckConstraint("duration_minutes > 0", name="appt_items_dur_pos"),
        Index("idx_appt_items_appt", "appointment_id"),
        Index("idx_appt_items_barber", "barber_id"),
        Index("idx_appt_items_service", "service_id"),
        Index("idx_appt_items_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # Denormalizado de `appointments.organization_id` (V17): antes, isolamento
    # dependia só de disciplina de JOIN — sem coluna própria, RLS direta não é
    # possível. Sempre igual ao da `Appointment` pai (setado no insert).
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    appointment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
    )
    service_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    barber_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="RESTRICT"), nullable=False
    )
    price_charged: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )

    appointment: Mapped["Appointment"] = relationship(back_populates="items")
    service: Mapped["Service"] = relationship(back_populates="appointment_items")
    barber: Mapped["Barber"] = relationship(back_populates="appointment_items")
