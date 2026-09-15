"""Carteira de crédito do cliente final (migration 0068).

Ledger append-only (molde `MembershipOfferEvent`/0065, `StockMovement`/0052):
o saldo do cliente é `SUM(amount)` das linhas, nunca uma coluna cacheada em
`Client` — evita dessincronização. `amount` é assinado: `credito_manual`/
`estorno` são positivos, `uso_pagamento` é negativo, `ajuste` pode ser
qualquer sinal (correção manual do gestor). Toda escrita passa por
`app/services/client_wallet.py` (nunca aqui no model).

`created_by_user_id` sem FK: mesma lógica do D-86/migration 0048 — fato
histórico, não trava se o usuário for removido depois.
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
from .enums import ClientWalletMovementType, pg_enum

if TYPE_CHECKING:
    from .client import Client
    from .organization import Organization


class ClientWalletMovement(Base):
    __tablename__ = "client_wallet_movements"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="client_wallet_movements_amount_nonzero"),
        Index("idx_client_wallet_movements_org_client", "organization_id", "client_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    movement_type: Mapped[ClientWalletMovementType] = mapped_column(
        pg_enum(ClientWalletMovementType, "client_wallet_movement_type"), nullable=False
    )
    reference_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    client: Mapped["Client"] = relationship()
