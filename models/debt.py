"""Contas a receber — débitos de clientes (migração da Trinks; migration 0023)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    Text,
    TIMESTAMP,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .client import Client
    from .organization import Organization


class ClientDebt(Base):
    __tablename__ = "client_debts"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="client_debts_amount_nonneg"),
        CheckConstraint("status IN ('aberto', 'pago')", name="client_debts_status_valid"),
        Index("idx_client_debts_org_status", "organization_id", "status"),
        Index("idx_client_debts_client", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # NULLABLE: o export da Trinks casa o cliente só por nome (pode não achar).
    client_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    client_name: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    debt_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    service_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    professional: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'aberto'")
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'trinks'")
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    organization: Mapped["Organization"] = relationship()
    client: Mapped[Optional["Client"]] = relationship()
