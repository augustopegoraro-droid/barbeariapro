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
from .enums import (
    MembershipOfferOutcome,
    MembershipOfferSurface,
    MembershipStatus,
    PlanAudience,
    pg_enum,
)

if TYPE_CHECKING:
    from .appointment import Appointment
    from .client import Client
    from .client_session import ClientSession
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
    # ── vitrine / segmentação (migration 0065) ────────────────────────────
    audience: Mapped[PlanAudience] = mapped_column(
        pg_enum(PlanAudience, "plan_audience"),
        nullable=False,
        server_default=text("'unissex'"),
    )
    # Rótulo livre de modalidade ("Corte & Barba", "Escova", "Manutenção"…).
    category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Frase curta de venda exibida na vitrine e no order bump.
    headline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Lista de benefícios extras exibíveis (["10% em produtos", "sem fila"]).
    perks: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Selo ("Mais vendido", "Melhor custo").
    badge: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Ordena a vitrine sem depender do preço.
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # Elegível a aparecer como order bump contextual.
    is_featured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
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
    # Quem executou o cancelamento (auditoria de ação destrutiva).
    canceled_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    client: Mapped["Client"] = relationship(back_populates="memberships")
    plan: Mapped[Optional["MembershipPlan"]] = relationship(back_populates="memberships")
    sold_by: Mapped[Optional["User"]] = relationship(foreign_keys=[sold_by_user_id])
    canceled_by: Mapped[Optional["User"]] = relationship(
        foreign_keys=[canceled_by_user_id]
    )
    usages: Mapped[List["MembershipUsage"]] = relationship(
        back_populates="membership", cascade="all, delete-orphan"
    )


class MembershipOrder(Base):
    """Pedido de compra ONLINE de assinatura (Stripe Connect, migration 0062).

    É o registro do dinheiro da venda pelo site público — deliberadamente fora
    de `payments` (que exige `Appointment`) e fora de `client_memberships` (que
    é o direito contratado, criado SÓ quando o webhook confirma o pagamento).

    Ciclo: `pending` (criado junto da Checkout Session) → `paid` (webhook
    confirmou; `client_membership_id` preenchido) | `failed` | `expired`
    (abandonado; cron `/internal/connect/expire-orders`) | `canceled`.

    `UNIQUE (provider, provider_session_id)` + `client_membership_id` não-nulo
    são as duas travas de idempotência do webhook: uma sessão de checkout gera
    no máximo um pedido, e um pedido gera no máximo uma assinatura.
    """

    __tablename__ = "membership_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'expired', 'canceled')",
            name="membership_orders_status_valid",
        ),
        CheckConstraint("amount_cents >= 0", name="membership_orders_amount_nonneg"),
        CheckConstraint(
            "application_fee_cents >= 0 AND application_fee_cents <= amount_cents",
            name="membership_orders_fee_within_amount",
        ),
        UniqueConstraint(
            "provider", "provider_session_id",
            name="membership_orders_provider_session_unique",
        ),
        Index("idx_membership_orders_org_status", "organization_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, unique=True, server_default=text("gen_random_uuid()")
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    client_session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("client_sessions.id", ondelete="SET NULL")
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False
    )
    # ── snapshots do plano no momento do pedido ────────────────────────────
    plan_name: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    included_uses: Mapped[Optional[int]] = mapped_column(Integer)
    duration_days: Mapped[Optional[int]] = mapped_column(Integer)
    combo_snapshot: Mapped[Optional[list]] = mapped_column(JSONB)
    # ── ciclo de vida / gateway ────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    provider: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'stripe_connect'")
    )
    provider_session_id: Mapped[Optional[str]] = mapped_column(Text)
    provider_payment_intent_id: Mapped[Optional[str]] = mapped_column(Text)
    provider_charge_id: Mapped[Optional[str]] = mapped_column(Text)
    connected_account_id: Mapped[Optional[str]] = mapped_column(Text)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    application_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'brl'")
    )
    payment_method_detail: Mapped[Optional[str]] = mapped_column(Text)
    client_membership_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("client_memberships.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    organization: Mapped["Organization"] = relationship()
    client: Mapped["Client"] = relationship()
    plan: Mapped["MembershipPlan"] = relationship()
    membership: Mapped[Optional["ClientMembership"]] = relationship()


class MembershipUsage(Base):
    """Histórico de uso de pacote + vínculo canônico 1:1 ao agendamento."""

    __tablename__ = "membership_usages"
    __table_args__ = (
        CheckConstraint("recognized_value >= 0", name="membership_usages_value_nonneg"),
        # Unicidade só para usos ATIVOS: um agendamento pode ter no máximo 1 uso
        # não-estornado. Estornos (reverted_at preenchido) ficam fora da unicidade,
        # permitindo re-vincular o mesmo agendamento depois de um estorno.
        Index(
            "membership_usages_appt_active_unique",
            "appointment_id",
            unique=True,
            postgresql_where=text("reverted_at IS NULL"),
        ),
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
    # Preenchido quando o atendimento é cancelado/faltou/estornado → restaura o saldo.
    reverted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Quem executou o estorno (auditoria — devolução do valor econômico do uso).
    reverted_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )

    organization: Mapped["Organization"] = relationship()
    membership: Mapped["ClientMembership"] = relationship(back_populates="usages")
    appointment: Mapped["Appointment"] = relationship()
    created_by: Mapped[Optional["User"]] = relationship(foreign_keys=[created_by_user_id])
    reverted_by: Mapped[Optional["User"]] = relationship(
        foreign_keys=[reverted_by_user_id]
    )


class MembershipOfferEvent(Base):
    """Log append-only de cada oferta de plano (order bump) exibida ao cliente.

    Uma linha por evento: a oferta foi mostrada (`shown`), aceita (`accepted`)
    ou recusada (`dismissed`), em uma das 3 superfícies (`booking` no checkout
    do agendamento, `conclusao` na conclusão do atendimento no painel,
    `assinatura` na página /assinatura). Alimenta o painel "Conversão do clube"
    e serve de guarda contra reexibir a mesma oferta no mesmo fluxo.

    `shown_amount` = valor avulso que o cliente estava prestes a pagar quando a
    oferta foi exibida (para medir a economia comunicada). GRANT só
    SELECT/INSERT — nunca se edita nem se apaga (migration 0065).
    """

    __tablename__ = "membership_offer_events"
    __table_args__ = (
        CheckConstraint(
            "shown_amount IS NULL OR shown_amount >= 0",
            name="membership_offer_events_amount_nonneg",
        ),
        Index(
            "idx_membership_offer_events_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "idx_membership_offer_events_org_surface",
            "organization_id",
            "surface",
            "outcome",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    surface: Mapped[MembershipOfferSurface] = mapped_column(
        pg_enum(MembershipOfferSurface, "membership_offer_surface"), nullable=False
    )
    outcome: Mapped[MembershipOfferOutcome] = mapped_column(
        pg_enum(MembershipOfferOutcome, "membership_offer_outcome"), nullable=False
    )
    plan_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("membership_plans.id", ondelete="SET NULL")
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="SET NULL")
    )
    client_session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("client_sessions.id", ondelete="SET NULL")
    )
    appointment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="SET NULL")
    )
    shown_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    context: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    plan: Mapped[Optional["MembershipPlan"]] = relationship()
