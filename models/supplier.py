"""Fornecedores e pedidos de compra — Fase 5 do módulo de Produtos/Estoque/
Vendas (plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Formaliza o fluxo de reposição de estoque com fornecedor e custo médio
preciso, complementando o ajuste manual da Fase 2. `PurchaseOrder` nasce
`rascunho`, pode ser marcado `enviado`, e o recebimento
(`POST /compras/{id}/receber`) atualiza `PurchaseOrderItem.qty_received` por
item, gera `stock_movements` tipo `entrada_compra` via
`app/services/inventory.py::apply_stock_movement` e recalcula
`ProductVariant.cost_avg` por média ponderada — tudo fora deste módulo
(lógica no router `app/api/fornecedores.py`, este arquivo é só schema).
`status` deriva de `qty_received` vs `qty_ordered` somados: nenhum item
recebido ainda = `rascunho`/`enviado`; algum item parcialmente recebido =
`recebido_parcial`; todos os itens com `qty_received >= qty_ordered` =
`recebido` (e `received_at` é carimbado).

Molde de `commission_transfer.py`/`sale.py`: `organization_id` com FK
CASCADE, RLS+FORCE, `created_by_user_id` sem FK (fato histórico, molde
D-86/0048).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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
from .enums import PurchaseOrderStatus, pg_enum

if TYPE_CHECKING:
    from .organization import Organization
    from .product import ProductVariant


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index("idx_suppliers_org_active", "organization_id", "active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    document: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="supplier")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("idx_purchase_orders_org_status", "organization_id", "status"),
        Index("idx_purchase_orders_org_supplier", "organization_id", "supplier_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        pg_enum(PurchaseOrderStatus, "purchase_order_status"),
        nullable=False,
        server_default=PurchaseOrderStatus.rascunho.value,
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    supplier: Mapped["Supplier"] = relationship(back_populates="purchase_orders")
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="purchase_order", order_by="PurchaseOrderItem.id", cascade="all, delete-orphan"
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("qty_ordered > 0", name="purchase_order_items_qty_ordered_positive"),
        CheckConstraint("qty_received >= 0", name="purchase_order_items_qty_received_nonneg"),
        CheckConstraint("unit_cost >= 0", name="purchase_order_items_unit_cost_nonneg"),
        Index("idx_purchase_order_items_org_po", "organization_id", "purchase_order_id"),
        Index("idx_purchase_order_items_org_variant", "organization_id", "variant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    qty_ordered: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    qty_received: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, server_default="0")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    organization: Mapped["Organization"] = relationship()
    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    variant: Mapped["ProductVariant"] = relationship()
