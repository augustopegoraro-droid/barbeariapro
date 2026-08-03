"""Catálogo de produtos vendáveis (lanches, bebidas, doces...) — Fase 1 do
módulo de Produtos/Estoque/Vendas.

Toda categoria/produto/variante segue o molde de `commission_transfer.py`:
`organization_id` com FK CASCADE, RLS por tenant, `active` para arquivar (nunca
deletar). Todo produto tem PELO MENOS UMA variante (produto "simples" ganha uma
variante default "Único") — preço/custo/estoque sempre pendura na variante,
nunca no produto, o que evita caso especial quando o produto tem variação real
(tamanho/sabor). `tracks_stock` no produto controla se as variantes participam
do controle de estoque (Fase 2) — produtos sem controle (ex. um café avulso)
nunca geram movimentação nem entram em alerta de mínimo.

`stock_qty`/`cost_avg`/`min_stock` já existem no schema desde a Fase 1 para não
exigir migration nova quando o Estoque (Fase 2) for implementado — ficam em 0
e sem uso até lá.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    SmallInteger,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization


class ProductCategory(Base):
    __tablename__ = "product_categories"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="product_categories_org_name_uq"),
        Index("idx_product_categories_org_active", "organization_id", "active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("idx_products_org_active", "organization_id", "active"),
        Index("idx_products_org_category", "organization_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit_of_measure: Mapped[str] = mapped_column(Text, nullable=False, server_default="un")
    tracks_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    category: Mapped[Optional["ProductCategory"]] = relationship(back_populates="products")
    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="product", order_by="ProductVariant.id"
    )


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("price >= 0", name="product_variants_price_nonneg"),
        CheckConstraint("cost_avg >= 0", name="product_variants_cost_avg_nonneg"),
        CheckConstraint("stock_qty >= 0", name="product_variants_stock_qty_nonneg"),
        CheckConstraint("min_stock >= 0", name="product_variants_min_stock_nonneg"),
        UniqueConstraint("organization_id", "sku", name="product_variants_org_sku_uq"),
        Index("idx_product_variants_org_product", "organization_id", "product_id"),
        Index("idx_product_variants_org_active", "organization_id", "active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # Fase 2 (Estoque): custo médio ponderado, saldo corrente e mínimo de
    # alerta. Já no schema desde a Fase 1 para não exigir migration nova.
    cost_avg: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")
    stock_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, server_default="0")
    min_stock: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    product: Mapped["Product"] = relationship(back_populates="variants")
