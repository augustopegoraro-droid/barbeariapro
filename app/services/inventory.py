"""Estoque — Fase 2 do módulo de Produtos/Estoque/Vendas.

Toda alteração de `ProductVariant.stock_qty` passa EXCLUSIVAMENTE por
`apply_stock_movement`: lock `FOR UPDATE` na variante (mesmo padrão de
`app/api/barbeiro.py::_load_appointment`, evita corrida entre duas
movimentações simultâneas levando o saldo a negativo), insere a linha
append-only em `stock_movements` e atualiza o saldo denormalizado. Nunca
decrementar/incrementar `stock_qty` em outro lugar do código.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ProductVariant, StockMovement, StockMovementType


async def apply_stock_movement(
    db: AsyncSession,
    *,
    organization_id: int,
    variant_id: int,
    movement_type: StockMovementType,
    qty_delta: Decimal,
    reason: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    unit_cost: Optional[Decimal] = None,
    created_by_user_id: Optional[int] = None,
) -> StockMovement:
    if qty_delta == 0:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY, "A quantidade da movimentação não pode ser zero."
        )

    variant = (
        await db.execute(
            select(ProductVariant)
            .where(ProductVariant.id == variant_id)
            .with_for_update(of=ProductVariant)
        )
    ).scalar_one_or_none()
    if variant is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Variação não encontrada.")

    qty_after = variant.stock_qty + qty_delta
    if qty_after < 0:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            f"Saldo insuficiente: estoque atual {variant.stock_qty}, movimentação de {qty_delta}.",
        )

    variant.stock_qty = qty_after
    movement = StockMovement(
        organization_id=organization_id,
        variant_id=variant.id,
        movement_type=movement_type,
        qty_delta=qty_delta,
        qty_after=qty_after,
        unit_cost=unit_cost,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(movement)
    await db.flush()
    return movement


async def low_stock_alerts(db: AsyncSession) -> list[dict]:
    """Variantes com saldo no mínimo ou abaixo dele (produto rastreado e ativo)."""
    from models import Product

    rows = (
        await db.execute(
            select(ProductVariant, Product.name)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                Product.tracks_stock.is_(True),
                ProductVariant.active.is_(True),
                Product.active.is_(True),
                ProductVariant.stock_qty <= ProductVariant.min_stock,
            )
            .order_by(ProductVariant.stock_qty)
        )
    ).all()
    return [
        {
            "variant_id": variant.id,
            "variant_name": variant.name,
            "product_name": product_name,
            "stock_qty": float(variant.stock_qty),
            "min_stock": float(variant.min_stock),
        }
        for variant, product_name in rows
    ]
