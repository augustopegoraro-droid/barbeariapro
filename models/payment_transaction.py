"""Transações de pagamento — histórico ANALÍTICO migrado da Trinks (migration 0035).

Cada linha é um pagamento/troco por comanda do relatório "Pagamentos/Estornos" da
Trinks: tipo e forma de pagamento, valor, taxa da operadora (desconto, tipicamente
negativo), valor líquido a receber e conta financeira. É histórico analítico —
NÃO se vincula a `appointments` (não temos o histórico completo) nem à tabela
`payments` (que exige `appointment_id`). Serve a relatórios de mix de formas de
pagamento, custo de cartão e recebíveis.

Mesmo molde de `cash_daily_closings` (0026): FK CASCADE + RLS por
`organization_id` + GRANT ao `barber_app`. Sem CHECK de sinal: o espelho preserva
valores negativos legítimos (desconto de operadora, troco).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    from .organization import Organization


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        Index(
            "idx_payment_transactions_org_date",
            "organization_id",
            "movement_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Data em que o dinheiro efetivamente movimentou (chave do de-para por período).
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Data do atendimento/venda que originou o pagamento.
    service_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expected_receipt_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # "Tipo de Forma de Pagamento": Crédito/Débito/PIX/À Vista/Transação Bancária/Pré-Pago.
    payment_type: Mapped[str] = mapped_column(Text, nullable=False)
    # "Forma de Pagamento": Visa/Mastercard/Dinheiro/PIX/Elo...
    payment_method: Mapped[str] = mapped_column(Text, nullable=False)
    installment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    anticipated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # "Tipo": Pagamento/Troco (categoria aberta — sem CHECK, dado migrado heterogêneo).
    entry_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Pagamento'")
    )
    comanda: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    operator_discount_pct: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    # Taxa da operadora em R$ (tipicamente negativa; positivo = R$ bruto == líquido).
    operator_discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    amount_to_receive: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    account: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'trinks'")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
