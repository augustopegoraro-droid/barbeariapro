"""Cardápio de serviços (catálogo corrente; histórico via snapshot no item)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    TIMESTAMP,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import ServiceCategory, pg_enum

if TYPE_CHECKING:
    from .appointment import AppointmentItem
    from .organization import Organization


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("default_duration_min > 0", name="services_duration_pos"),
        CheckConstraint("price >= 0", name="services_price_nonneg"),
        CheckConstraint("cost >= 0", name="services_cost_nonneg"),
        Index("idx_services_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[ServiceCategory] = mapped_column(
        pg_enum(ServiceCategory, "service_category"), nullable=False
    )
    default_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="services")
    appointment_items: Mapped[List["AppointmentItem"]] = relationship(
        back_populates="service"
    )
