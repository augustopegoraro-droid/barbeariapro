"""Sugestão de compra de produto — camada de dados (sob RLS do tenant).

Usada pelo router `/compras-sugeridas` e pelo dispatch do Kernel IA. Todas as
queries rodam na sessão do tenant (RLS filtra por `organization_id`). Molde de
`app/services/reschedule.py` (mesmo desenho de "solicitação pendente de
aprovação" do D-57, estendido para compras no D-98).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Product, ProductPurchaseRequest, ProductVariant

_TERMINAL = {"aprovada": True, "recusada": True}


async def create_request(
    db: AsyncSession,
    *,
    organization_id: int,
    requested_by_user_id: Optional[int],
    variant_id: Optional[int] = None,
    product_name: Optional[str] = None,
    qty_suggested: Optional[Decimal] = None,
    reason: Optional[str] = None,
    source: str = "app",
) -> ProductPurchaseRequest:
    if variant_id is None and not (product_name and product_name.strip()):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe a variação (`variant_id`) ou o nome do produto.",
        )
    req = ProductPurchaseRequest(
        organization_id=organization_id,
        variant_id=variant_id,
        product_name=(product_name.strip() if product_name else None),
        qty_suggested=qty_suggested,
        reason=reason,
        status="pendente",
        source=source,
        requested_by_user_id=requested_by_user_id,
    )
    db.add(req)
    await db.flush()
    await db.refresh(req)
    return req


async def list_requests(
    db: AsyncSession, *, status: Optional[str] = None
) -> list[ProductPurchaseRequest]:
    stmt = (
        select(ProductPurchaseRequest)
        .options(selectinload(ProductPurchaseRequest.variant).selectinload(ProductVariant.product))
        .order_by(
            ProductPurchaseRequest.created_at.desc(),
            ProductPurchaseRequest.id.desc(),
        )
    )
    if status is not None:
        stmt = stmt.where(ProductPurchaseRequest.status == status)
    return list((await db.execute(stmt)).scalars().all())


async def count_pending(db: AsyncSession) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(ProductPurchaseRequest)
            .where(ProductPurchaseRequest.status == "pendente")
        )
    ).scalar_one()


async def review_request(
    db: AsyncSession,
    *,
    request_id: int,
    approve: bool,
    reviewed_by_user_id: int,
    note: Optional[str] = None,
    purchase_order_id: Optional[int] = None,
) -> ProductPurchaseRequest:
    """Aprova ou recusa um pedido pendente. 404 se não existe (ou é de outro
    tenant — RLS); 409 se já foi decidido."""
    req = (
        await db.execute(
            select(ProductPurchaseRequest)
            .where(ProductPurchaseRequest.id == request_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Sugestão de compra não encontrada.",
        )
    if req.status in _TERMINAL:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Sugestão já está '{req.status}'.",
        )
    req.status = "aprovada" if approve else "recusada"
    req.reviewed_by_user_id = reviewed_by_user_id
    req.reviewed_at = func.now()
    req.review_note = note
    if purchase_order_id is not None:
        req.purchase_order_id = purchase_order_id
    await db.flush()
    await db.refresh(req)
    return req


async def resolve_variant_by_name(db: AsyncSession, name: str) -> Optional[ProductVariant]:
    """Busca uma variação ativa por nome (produto ou variação), case-insensitive.
    Retorna a variação só se houver EXATAMENTE UMA correspondência — o Kernel IA
    nunca deve adivinhar entre várias, o pedido fica só com `product_name` nesse
    caso (sem alucinar um `variant_id`)."""
    needle = f"%{name.strip()}%"
    stmt = (
        select(ProductVariant)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(ProductVariant.active.is_(True))
        .where(Product.active.is_(True))
        .where(or_(Product.name.ilike(needle), ProductVariant.name.ilike(needle)))
        .limit(2)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows[0] if len(rows) == 1 else None
