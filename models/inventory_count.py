"""Contagem física de estoque — Fase 6 do módulo de Produtos/Estoque/Vendas
(plano em /Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Operação periódica (não do dia a dia): abrir uma contagem congela o
`stock_qty` corrente de cada variação rastreada em `expected_qty`; a Raquel
preenche `counted_qty` por item ao longo da conferência; finalizar gera, para
cada item com divergência, uma linha em `stock_movements` tipo `inventario`
via `app/services/inventory.py::apply_stock_movement` com
`qty_delta = counted_qty - expected_qty` — nunca escreve `stock_qty`
diretamente aqui (mesma regra da Fase 2).

Molde de `supplier.py`/`sale.py`: `organization_id` com FK CASCADE, RLS+FORCE,
`created_by_user_id` sem FK (fato histórico, molde D-86/0048).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import InventoryCountStatus, pg_enum

if TYPE_CHECKING:
    from .organization import Organization
    from .product import ProductVariant


class InventoryCount(Base):
    __tablename__ = "inventory_counts"
    __table_args__ = (
        Index("idx_inventory_counts_org_status", "organization_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[InventoryCountStatus] = mapped_column(
        pg_enum(InventoryCountStatus, "inventory_count_status"),
        nullable=False,
        server_default=InventoryCountStatus.aberto.value,
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    finalized_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    organization: Mapped["Organization"] = relationship()
    items: Mapped[list["InventoryCountItem"]] = relationship(
        back_populates="inventory_count", order_by="InventoryCountItem.id", cascade="all, delete-orphan"
    )


class InventoryCountItem(Base):
    __tablename__ = "inventory_count_items"
    __table_args__ = (
        UniqueConstraint(
            "inventory_count_id", "variant_id", name="inventory_count_items_count_variant_uq"
        ),
        Index("idx_inventory_count_items_org_count", "organization_id", "inventory_count_id"),
        Index("idx_inventory_count_items_org_variant", "organization_id", "variant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    inventory_count_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("inventory_counts.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    expected_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    counted_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)

    organization: Mapped["Organization"] = relationship()
    inventory_count: Mapped["InventoryCount"] = relationship(back_populates="items")
    variant: Mapped["ProductVariant"] = relationship()
