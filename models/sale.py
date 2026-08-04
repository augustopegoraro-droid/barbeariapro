"""Venda de produtos — Fase 3 do módulo de Produtos/Estoque/Vendas
(plano em /Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

`Sale`/`SaleItem`/`SalePayment` são um domínio paralelo a `Appointment`/
`AppointmentItem`/`Payment` — nunca os alteram nem exigem FK deles.
`appointment_id` é opcional: `NULL` é venda de balcão pura, preenchido é uma
venda anexada a um atendimento (mostrada como bloco extra na conclusão, sem
tocar em `AppointmentItem`). `client_id` também é opcional (balcão pode ser
anônimo).

`unit_price_charged`/`unit_cost_snapshot` em `SaleItem` são SNAPSHOTS do preço/
custo médio da variante no momento da venda — o lucro de uma venda antiga não
muda se o preço/custo do produto for editado depois (mesmo padrão de
`AppointmentItem.price_charged` e `CommissionTransfer.amount`).

Baixa de estoque acontece na confirmação da venda (`POST /vendas`), síncrona,
via `app/services/inventory.py::apply_stock_movement` com
`reference_type="sale"` — nunca aqui no model.

`created_by_user_id` sem FK: mesma lógica do D-86/migration 0048 (fato
histórico, não trava se o usuário for removido depois).
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
from .enums import PaymentMethod, SaleStatus, pg_enum

if TYPE_CHECKING:
    from .appointment import Appointment
    from .client import Client
    from .organization import Organization
    from .product import ProductVariant
    from .unit import Unit


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="sales_total_amount_nonneg"),
        Index("idx_sales_org_created", "organization_id", "created_at"),
        Index("idx_sales_org_appointment", "organization_id", "appointment_id"),
        Index("idx_sales_org_client", "organization_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    appointment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[SaleStatus] = mapped_column(
        pg_enum(SaleStatus, "sale_status"), nullable=False, server_default=SaleStatus.concluida.value
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    unit: Mapped["Unit"] = relationship()
    client: Mapped[Optional["Client"]] = relationship()
    appointment: Mapped[Optional["Appointment"]] = relationship()
    items: Mapped[list["SaleItem"]] = relationship(
        back_populates="sale", order_by="SaleItem.id", cascade="all, delete-orphan"
    )
    payments: Mapped[list["SalePayment"]] = relationship(
        back_populates="sale", order_by="SalePayment.id", cascade="all, delete-orphan"
    )


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="sale_items_qty_positive"),
        CheckConstraint("unit_price_charged >= 0", name="sale_items_price_nonneg"),
        CheckConstraint("unit_cost_snapshot >= 0", name="sale_items_cost_nonneg"),
        Index("idx_sale_items_org_sale", "organization_id", "sale_id"),
        Index("idx_sale_items_org_variant", "organization_id", "variant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    sale_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price_charged: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit_cost_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")

    organization: Mapped["Organization"] = relationship()
    sale: Mapped["Sale"] = relationship(back_populates="items")
    variant: Mapped["ProductVariant"] = relationship()


class SalePayment(Base):
    __tablename__ = "sale_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="sale_payments_amount_positive"),
        Index("idx_sale_payments_org_sale", "organization_id", "sale_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    sale_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(
        pg_enum(PaymentMethod, "payment_method"), nullable=False
    )
    paid_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    sale: Mapped["Sale"] = relationship(back_populates="payments")
