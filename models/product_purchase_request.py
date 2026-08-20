"""Sugestão de compra de produto (barbeiro/recepção → aprovação do gestor).

Quem opera o dia a dia nota estoque baixo e SUGERE a compra sem executá-la —
só owner/manager (`purchases.manage`) compra de fato (D-93). O pedido fica
``pendente`` até um gestor aprovar/recusar. RLS por ``organization_id`` +
FORCE (migration 0057).
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization
    from .product import ProductVariant

PURCHASE_REQUEST_STATUSES = ("pendente", "aprovada", "recusada")


class ProductPurchaseRequest(Base):
    __tablename__ = "product_purchase_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pendente', 'aprovada', 'recusada')",
            name="purchase_request_status_valid",
        ),
        CheckConstraint(
            "source IN ('app', 'kernel_ia')",
            name="purchase_request_source_valid",
        ),
        CheckConstraint(
            "qty_suggested IS NULL OR qty_suggested > 0",
            name="purchase_request_qty_positive",
        ),
        CheckConstraint(
            "variant_id IS NOT NULL OR product_name IS NOT NULL",
            name="purchase_request_target_present",
        ),
        Index("idx_purchase_requests_org_status", "organization_id", "status"),
        Index("idx_purchase_requests_org_variant", "organization_id", "variant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Alvo: a variação (quando conhecida) OU o nome livre (Kernel IA não conhece IDs).
    variant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=True
    )
    product_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    qty_suggested: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pendente'")
    )
    # Origem do pedido: 'kernel_ia' (chat) ou 'app' (formulário).
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'app'"))
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Preenchido quando o gestor materializa a sugestão num pedido formal (D-93).
    purchase_order_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    variant: Mapped[Optional["ProductVariant"]] = relationship()
