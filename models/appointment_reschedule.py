"""Pedidos de remarcação de atendimentos (barbeiro → aprovação do gestor).

O barbeiro solicita remarcar os PRÓPRIOS atendimentos num período que escolhe; o
pedido fica ``pendente`` até um gestor aprovar/recusar (aparece no sino da tela do
gestor). A aprovação NÃO move os atendimentos automaticamente — isso é ação
posterior do gestor (follow-up). RLS por ``organization_id`` (migration 0024).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    TIMESTAMP,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .barber import Barber
    from .organization import Organization

# Status possíveis (Text + CheckConstraint, mesmo padrão de client_debts).
RESCHEDULE_STATUSES = ("pendente", "aprovada", "recusada")


class AppointmentRescheduleRequest(Base):
    __tablename__ = "appointment_reschedule_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pendente', 'aprovada', 'recusada')",
            name="reschedule_status_valid",
        ),
        Index("idx_reschedule_org_status", "organization_id", "status"),
        Index("idx_reschedule_barber", "barber_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    barber_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False
    )
    # Quem criou (o barbeiro logado). SET NULL para sobreviver à remoção do usuário.
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Período que o barbeiro quer remarcar. NULLABLE: um pedido vindo do Kernel IA
    # (texto livre) pode não trazer datas estruturadas — o período fica no `reason`.
    period_start: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    period_end: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pendente'")
    )
    # Origem do pedido: 'kernel_ia' (texto livre) ou 'app' (formulário).
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'app'"))
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    barber: Mapped["Barber"] = relationship()
