"""Snapshot de fidelidade do cliente — atualizado a cada agendamento concluído."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import LoyaltyCategoria, LoyaltyNivel, LoyaltyStatus, pg_enum

if TYPE_CHECKING:
    from .barber import Barber
    from .client import Client
    from .service import Service


class ClientLoyalty(Base):
    __tablename__ = "client_loyalty"
    __table_args__ = (
        Index("idx_client_loyalty_org_nivel", "organization_id", "nivel"),
        Index("idx_client_loyalty_org_status", "organization_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    visit_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    total_spent: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    last_visit_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    nivel: Mapped[LoyaltyNivel] = mapped_column(
        pg_enum(LoyaltyNivel, "loyalty_nivel"), nullable=False, server_default="novo"
    )
    status: Mapped[LoyaltyStatus] = mapped_column(
        pg_enum(LoyaltyStatus, "loyalty_status"), nullable=False, server_default="ativo"
    )
    categoria: Mapped[Optional[LoyaltyCategoria]] = mapped_column(
        pg_enum(LoyaltyCategoria, "loyalty_categoria"), nullable=True
    )
    preferred_barber_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="SET NULL"), nullable=True
    )
    preferred_service_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    client: Mapped["Client"] = relationship(back_populates="loyalty")
    preferred_barber: Mapped[Optional["Barber"]] = relationship(
        foreign_keys=[preferred_barber_id]
    )
    preferred_service: Mapped[Optional["Service"]] = relationship(
        foreign_keys=[preferred_service_id]
    )
