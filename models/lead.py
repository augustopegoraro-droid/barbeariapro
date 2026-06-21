"""CRM: leads (funil/Kanban) e seu histórico de eventos.

Aditivo e isolado por organização (RLS `tenant_isolation`, igual às demais
tabelas tenant). Não altera nenhuma tabela existente.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    TIMESTAMP,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import ContactChannel, LeadStage, pg_enum

if TYPE_CHECKING:
    pass


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("idx_leads_org_stage", "organization_id", "stage"),
        Index("idx_leads_org_position", "organization_id", "stage", "position"),
        Index("idx_leads_client", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="SET NULL")
    )
    # Quando o lead vira cliente cadastrado, aponta para ele (não obrigatório).
    client_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_e164: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[ContactChannel]] = mapped_column(
        pg_enum(ContactChannel, "contact_channel")
    )
    stage: Mapped[LeadStage] = mapped_column(
        pg_enum(LeadStage, "lead_stage"),
        nullable=False,
        server_default=text("'novo_contato'"),
    )
    # Ordenação do card dentro da coluna do Kanban.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    assigned_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    events: Mapped[List["LeadEvent"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="LeadEvent.created_at",
    )


class LeadEvent(Base):
    """Histórico de movimentação do lead (auditoria e base p/ automações)."""

    __tablename__ = "lead_events"
    __table_args__ = (
        Index("idx_lead_events_lead", "lead_id"),
        Index("idx_lead_events_org_created", "organization_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 'created' | 'stage_changed' | 'note' | 'contacted'
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_stage: Mapped[Optional[LeadStage]] = mapped_column(
        pg_enum(LeadStage, "lead_stage")
    )
    to_stage: Mapped[Optional[LeadStage]] = mapped_column(
        pg_enum(LeadStage, "lead_stage")
    )
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    lead: Mapped["Lead"] = relationship(back_populates="events")
