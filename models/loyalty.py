"""Snapshot de fidelidade do cliente — atualizado a cada agendamento concluído."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (
    LoyaltyCategoria,
    LoyaltyLedgerType,
    LoyaltyNivel,
    LoyaltyStatus,
    LoyaltyVoucherStatus,
    pg_enum,
)

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
    # Fidelidade por pontos (Fase 2): saldo materializado do ledger + tier derivado.
    points_balance: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    current_tier_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("loyalty_tiers.id", ondelete="SET NULL"), nullable=True
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
    current_tier: Mapped[Optional["LoyaltyTier"]] = relationship(foreign_keys=[current_tier_id])


class LoyaltyTier(Base):
    """Ladder de níveis configurável por org. O tier do cliente = maior tier
    cujo `min_points` ele alcança (points-driven)."""

    __tablename__ = "loyalty_tiers"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_loyalty_tiers_org_name"),
        CheckConstraint("min_points >= 0", name="loyalty_tiers_min_points_nonneg"),
        CheckConstraint(
            "discount_pct >= 0 AND discount_pct <= 1", name="loyalty_tiers_discount_range"
        ),
        Index("idx_loyalty_tiers_org", "organization_id", "min_points"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    min_points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0")
    perks: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class LoyaltyRule(Base):
    """Regra de ganho/resgate de pontos por org (1 linha por organização)."""

    __tablename__ = "loyalty_rules"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    points_per_brl: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, server_default="1")
    points_per_visit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    redemption_brl_per_point: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, server_default="1"
    )
    expiration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class LoyaltyVoucher(Base):
    """Crédito gerado por resgate de pontos (consumo no checkout: fase futura)."""

    __tablename__ = "loyalty_vouchers"
    __table_args__ = (
        CheckConstraint("amount_brl >= 0", name="loyalty_vouchers_amount_nonneg"),
        CheckConstraint("points_spent >= 0", name="loyalty_vouchers_points_nonneg"),
        Index("idx_loyalty_vouchers_client", "organization_id", "client_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    amount_brl: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    points_spent: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[LoyaltyVoucherStatus] = mapped_column(
        pg_enum(LoyaltyVoucherStatus, "loyalty_voucher_status"),
        nullable=False,
        server_default="ativo",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    consumed_appointment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )


class LoyaltyPointEntry(Base):
    """Lançamento APPEND-ONLY do ledger de pontos — fonte de verdade do saldo."""

    __tablename__ = "loyalty_point_ledger"
    __table_args__ = (
        CheckConstraint("balance_after >= 0", name="loyalty_ledger_balance_nonneg"),
        Index("idx_loyalty_ledger_client", "organization_id", "client_id", "created_at"),
        Index(
            "uq_loyalty_earn_per_appointment",
            "organization_id",
            "ref_appointment_id",
            unique=True,
            postgresql_where=text("type = 'earn' AND ref_appointment_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[LoyaltyLedgerType] = mapped_column(
        pg_enum(LoyaltyLedgerType, "loyalty_ledger_type"), nullable=False
    )
    points_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    ref_appointment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    ref_voucher_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("loyalty_vouchers.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
