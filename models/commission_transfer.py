"""Repasse de comissão entre barbeiros — lançamento vinculado a um item de
atendimento concluído (migration 0050).

O gestor registra que uma fração da comissão de um `AppointmentItem` (já
calculada como `price_charged × Barber.commission_pct`) vai para OUTRO
barbeiro além do dono do item — ex.: atendimento a 4 mãos, acordo entre
profissionais. Não altera `barber_id` do item nem `commission_pct` de
ninguém: é uma correção lançada por cima, aplicada em `management.py` na
hora de agregar comissão por período.

`amount` é um SNAPSHOT do valor calculado no momento do lançamento — a
história não deve mudar se o `commission_pct` do barbeiro for editado depois.

`created_by_user_id` sem FK: segue a mesma lógica do D-86/migration 0048
(`audit_logs.actor_user_id`) — é um fato histórico de quem lançou, não deve
travar/zerar se o usuário for removido depois.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .appointment import AppointmentItem
    from .barber import Barber
    from .organization import Organization


class CommissionTransfer(Base):
    __tablename__ = "commission_transfers"
    __table_args__ = (
        CheckConstraint("pct > 0 AND pct <= 1", name="commission_transfers_pct_range"),
        CheckConstraint("amount >= 0", name="commission_transfers_amount_nonneg"),
        CheckConstraint(
            "from_barber_id <> to_barber_id", name="commission_transfers_distinct_barbers"
        ),
        Index("idx_commission_transfers_org_item", "organization_id", "appointment_item_id"),
        Index("idx_commission_transfers_org_to", "organization_id", "to_barber_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    appointment_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("appointment_items.id", ondelete="RESTRICT"), nullable=False
    )
    from_barber_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="RESTRICT"), nullable=False
    )
    to_barber_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="RESTRICT"), nullable=False
    )
    pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    appointment_item: Mapped["AppointmentItem"] = relationship()
    from_barber: Mapped["Barber"] = relationship(foreign_keys=[from_barber_id])
    to_barber: Mapped["Barber"] = relationship(foreign_keys=[to_barber_id])
