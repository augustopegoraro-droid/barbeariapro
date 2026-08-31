"""Caixa vivo — turno (abrir/fechar em tempo real) + ledger de movimentos
(migration 0063, D-101).

Não confundir com `cash_closing.py` (`CashDailyClosing`) — aquele é o histórico
de fechamento diário **migrado da Trinks** (migration 0026, D-59), read-only.
Aqui é o caixa operado ao vivo pela recepção.

- `CashSession`: um turno. `opening_float` é o troco inicial; ao fechar,
  `counted_amount` (dinheiro contado), `expected_amount` (saldo esperado
  calculado) e `difference` (contado − esperado) são **snapshots** congelados
  no fechamento. No máximo 1 sessão `aberto` por unidade (índice único parcial
  na migration). `opened_by_user_id`/`closed_by_user_id` sem FK — fato
  histórico, molde `audit_logs.actor_user_id` (D-86/0048).
- `CashMovement`: ledger **append-only** (a migration só concede SELECT/INSERT
  ao `barber_app`). Correção/estorno = novo movimento `ajuste` (único tipo que
  aceita `amount` negativo). Idempotência: índice único parcial em
  `(organization_id, reference_type, reference_id)` para `reference_type IN
  ('payment','sale','expense')` — o mesmo `Payment`/`Sale`/`Expense` nunca
  posta 2×.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

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
from .enums import CashMovementType, CashSessionStatus, pg_enum

if TYPE_CHECKING:
    from .organization import Organization
    from .unit import Unit


class CashSession(Base):
    __tablename__ = "cash_sessions"
    __table_args__ = (
        CheckConstraint("opening_float >= 0", name="cash_sessions_opening_float_nonneg"),
        Index("idx_cash_sessions_org_opened", "organization_id", "opened_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[CashSessionStatus] = mapped_column(
        pg_enum(CashSessionStatus, "cash_session_status"),
        nullable=False,
        server_default=CashSessionStatus.aberto.value,
    )
    opened_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    opened_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    opening_float: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    closed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    counted_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    expected_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    closing_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    unit: Mapped["Unit"] = relationship()
    movements: Mapped[List["CashMovement"]] = relationship(
        back_populates="session", order_by="CashMovement.created_at"
    )


class CashMovement(Base):
    __tablename__ = "cash_movements"
    __table_args__ = (
        CheckConstraint(
            "amount >= 0 OR type = 'ajuste'", name="cash_movements_amount_sign"
        ),
        Index(
            "idx_cash_movements_org_session",
            "organization_id",
            "session_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cash_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[CashMovementType] = mapped_column(
        pg_enum(CashMovementType, "cash_movement_type"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(Text)
    reference_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped["CashSession"] = relationship(back_populates="movements")
