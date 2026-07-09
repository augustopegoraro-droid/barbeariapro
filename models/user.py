"""Autenticação e permissão: User, UserUnit (papel por unidade)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Identity,
    Index,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import UnitRole, pg_enum

if TYPE_CHECKING:
    from .appointment import Appointment
    from .barber import Barber
    from .organization import Organization
    from .unit import Unit


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="users_email_per_org"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Telefone canônico (E.164) — usado no gating por telefone do Agente Gestor.
    phone_e164: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # True após reset administrativo (D-68) — força troca de senha no próximo login.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="users")
    unit_links: Mapped[List["UserUnit"]] = relationship(back_populates="user")
    created_appointments: Mapped[List["Appointment"]] = relationship(
        back_populates="created_by"
    )


class UserUnit(Base):
    __tablename__ = "user_units"
    __table_args__ = (
        Index("idx_user_units_unit", "unit_id"),
        Index("idx_user_units_barber", "barber_id"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("units.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[UnitRole] = mapped_column(
        pg_enum(UnitRole, "unit_role"), nullable=False
    )
    barber_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="SET NULL")
    )

    user: Mapped["User"] = relationship(back_populates="unit_links")
    unit: Mapped["Unit"] = relationship(back_populates="user_links")
    barber: Mapped[Optional["Barber"]] = relationship(back_populates="user_links")
