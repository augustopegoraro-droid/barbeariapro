"""Mensalidade/assinatura do CLIENTE FINAL com pacotes (combo fixo).

NÃO confundir com `Plan`/`Subscription` em `organization.py`, que são o billing
do tenant SaaS. Aqui o cliente final contrata um `MembershipPlan` (combo fixo +
N usos), vira um `ClientMembership` com vigência e saldo, e cada uso de pacote
gera um `MembershipUsage` ligado 1:1 a um `Appointment`.

Imutabilidade: a assinatura grava *snapshots* do plano no momento da venda
(`price_paid`, `included_uses`, `unit_recognized_value`, `combo_snapshot`,
`duration_days`), espelhando o padrão de `AppointmentItem.price_charged` — editar
o plano depois não altera assinaturas já vendidas.
"""

from __future__ import annotations

import uuid
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
    SmallInteger,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import MembershipStatus, pg_enum

if TYPE_CHECKING:
    from .appointment import Appointment
    from .client import Client
    from .organization import Organization
    from .service import Service
    from .user import User


class MembershipPlan(Base):
    """Catálogo de planos de mensalidade (combo fixo + N usos)."""

    __tablename__ = "membership_plans"
    __table_args__ = (
        CheckConstraint("price >= 0", name="membership_plans_price_nonneg"),
        CheckConstraint(
            "included_uses IS NULL OR included_uses > 0",
            name="membership_plans_uses_pos",
        ),
        CheckConstraint("duration_days > 0", name="membership_plans_duration_pos"),
        CheckConstraint(
            "unlimited_use_value IS NULL OR unlimited_use_value >= 0",
            name="membership_plans_unit_value_nonneg",
        ),
        Index("idx_membership_plans_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # NULL = ilimitado.
    included_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # Valor reconhecido por uso quando ilimitado (rateio não se aplica).
    unlimited_use_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    organization: Mapped["Organization"] = relationship()
    items: Mapped[List["MembershipPlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    memberships: Mapped[List["ClientMembership"]] = relationship(back_populates="plan")


class MembershipPlanItem(Base):
    """Composição do combo: serviços que formam 1 pacote do plano."""

    __tablename__ = "membership_plan_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "service_id", name="membership_plan_item_unique"),
        Index("idx_membership_plan_items_plan", "plan_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("membership_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    service_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )

    plan: Mapped["MembershipPlan"] = relationship(back_populates="items")
    service: Mapped["Service"] = relationship()


class ClientMembership(Base):
    """Assinatura contratada por um cliente (com snapshots imutáveis do plano)."""

    __tablename__ = "client_memberships"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="client_memberships_period_valid"),
        CheckConstraint("price_paid >= 0", name="client_memberships_price_nonneg"),
        CheckConstraint("used_uses >= 0", name="client_memberships_used_nonneg"),
        CheckConstraint(
            "included_uses IS NULL OR used_uses <= included_uses",
            name="client_memberships_used_within_limit",
        ),
        Index("idx_client_memberships_client", "client_id"),
        Index("idx_client_memberships_org_status", "organization_id", "status"),
        Index(
            "idx_client_memberships_active",
            "organization_id",
            "client_id",
            postgresql_where=text("status = 'ativa'"),
        ),
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
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    # Referência ao catálogo; a imutabilidade vem dos snapshots abaixo.
    # NULL = pacote personalizado (montado direto para o cliente, sem plano de
    # catálogo). A imutabilidade segue garantida pelos snapshots abaixo.
    plan_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("membership_plans.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        pg_enum(MembershipStatus, "membership_status"),
        nullable=False,
        server_default=text("'ativa'"),
    )
    start_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    # ── snapshots no momento da venda ──────────────────────────────────────
    price_paid: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    included_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used_uses: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    unit_recognized_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    combo_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # ───────────────────────────────────────────────────────────────────────
    sold_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    canceled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    client: Mapped["Client"] = relationship(back_populates="memberships")
    plan: Mapped[Optional["MembershipPlan"]] = relationship(back_populates="memberships")
    sold_by: Mapped[Optional["User"]] = relationship()
    usages: Mapped[List["MembershipUsage"]] = relationship(
        back_populates="membership", cascade="all, delete-orphan"
    )


class MembershipUsage(Base):
    """Histórico de uso de pacote + vínculo canônico 1:1 ao agendamento."""

    __tablename__ = "membership_usages"
    __table_args__ = (
        CheckConstraint("recognized_value >= 0", name="membership_usages_value_nonneg"),
        UniqueConstraint("appointment_id", name="membership_usages_appt_unique"),
        Index("idx_membership_usages_membership", "membership_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    membership_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_memberships.id", ondelete="RESTRICT"),
        nullable=False,
    )
    appointment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=False
    )
    recognized_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    used_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    # Preenchido quando o atendimento é cancelado/faltou → restaura o saldo.
    reverted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )

    organization: Mapped["Organization"] = relationship()
    membership: Mapped["ClientMembership"] = relationship(back_populates="usages")
    appointment: Mapped["Appointment"] = relationship()
    created_by: Mapped[Optional["User"]] = relationship()
