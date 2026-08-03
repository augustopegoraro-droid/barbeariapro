"""Movimentação de estoque — Fase 2 do módulo de Produtos/Estoque/Vendas
(plano em /Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Append-only: nenhuma linha é editada/apagada, é a fonte de auditoria do
histórico de estoque. `qty_delta` já embute o sinal (positivo = entrada,
negativo = saída/perda); `qty_after` é o snapshot do saldo resultante da
variante logo após a movimentação. Toda escrita passa exclusivamente por
`app/services/inventory.py::apply_stock_movement` (lock `FOR UPDATE` na
variante, mesmo padrão de `app/api/barbeiro.py::_load_appointment`) — nunca
alterar `ProductVariant.stock_qty` em outro lugar do código.

`created_by_user_id` sem FK: mesma lógica do D-86/migration 0048
(`audit_logs.actor_user_id`) — fato histórico, não trava se o usuário for
removido depois.
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
from .enums import StockMovementType, pg_enum

if TYPE_CHECKING:
    from .organization import Organization
    from .product import ProductVariant


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("qty_delta <> 0", name="stock_movements_qty_delta_nonzero"),
        Index("idx_stock_movements_org_variant", "organization_id", "variant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    movement_type: Mapped[StockMovementType] = mapped_column(
        pg_enum(StockMovementType, "stock_movement_type"), nullable=False
    )
    qty_delta: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    qty_after: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    variant: Mapped["ProductVariant"] = relationship()
