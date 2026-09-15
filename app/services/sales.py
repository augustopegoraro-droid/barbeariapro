"""Núcleo de criação de venda de produto — extraído de `app/api/vendas.py`
para ser reaproveitado pelo checkout único de conclusão de atendimento
(`app/api/barbeiro.py::concluir_atendimento`) e pelo router `/vendas`.

`build_sale` só cria `Sale`/`SaleItem` e baixa estoque — NÃO cria
`SalePayment` nem toca no caixa. Cada chamador decide como os pagamentos são
alocados (o router `/vendas` usa a lista recebida direto; o checkout único
aloca uma fatia do split geral — ver `app/api/barbeiro.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.inventory import apply_stock_movement
from models import Product, ProductVariant, Sale, SaleItem, SaleStatus, StockMovementType


@dataclass(frozen=True)
class SaleItemIn:
    variant_id: int
    qty: Decimal


async def build_sale(
    db: AsyncSession,
    *,
    organization_id: int,
    unit_id: int,
    client_id: Optional[int],
    appointment_id: Optional[int],
    items: list[SaleItemIn],
    created_by_user_id: int,
) -> Sale:
    """Cria a `Sale` (status `concluida`) + `SaleItem`s + baixa de estoque.
    Levanta 404/422 se alguma variação não existir ou houver duplicata."""
    variant_ids = [i.variant_id for i in items]
    if len(variant_ids) != len(set(variant_ids)):
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Cada variação só pode aparecer uma vez por venda — some as quantidades.",
        )

    variant_rows = (
        await db.execute(
            select(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(ProductVariant.id.in_(variant_ids))
        )
    ).all()
    variants_by_id = {v.id: (v, p) for v, p in variant_rows}

    missing = [i.variant_id for i in items if i.variant_id not in variants_by_id]
    if missing:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Variação(ões) não encontrada(s): {missing}.")

    total_amount = sum(
        (variants_by_id[i.variant_id][0].price * i.qty for i in items), Decimal("0")
    ).quantize(Decimal("0.01"))

    sale = Sale(
        organization_id=organization_id,
        unit_id=unit_id,
        client_id=client_id,
        appointment_id=appointment_id,
        status=SaleStatus.concluida,
        total_amount=total_amount,
        created_by_user_id=created_by_user_id,
    )
    db.add(sale)
    await db.flush()

    for item in items:
        variant, product = variants_by_id[item.variant_id]
        db.add(
            SaleItem(
                organization_id=organization_id,
                sale_id=sale.id,
                variant_id=variant.id,
                qty=item.qty,
                unit_price_charged=variant.price,
                unit_cost_snapshot=variant.cost_avg,
            )
        )
        if product.tracks_stock:
            await apply_stock_movement(
                db,
                organization_id=organization_id,
                variant_id=variant.id,
                movement_type=StockMovementType.saida_venda,
                qty_delta=-item.qty,
                reference_type="sale",
                reference_id=sale.id,
                created_by_user_id=created_by_user_id,
            )

    await db.flush()
    return sale
