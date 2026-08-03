"""Estoque — Fase 2 do módulo de Produtos/Estoque/Vendas (plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Entrada/saída de mercadoria via ajuste manual (sem depender de Compras, que é
Fase 5) + alertas de mínimo. Baixa automática por venda fica para a Fase 3
(`sales`) — este router não cria movimentação nenhuma sozinho, só expõe o
lançamento manual e a leitura do histórico/alertas.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.services.audit import record_event
from app.services.inventory import apply_stock_movement, low_stock_alerts
from models import Product, ProductVariant, StockMovement, StockMovementType, User

router = APIRouter(prefix="/estoque", tags=["estoque"])

_MANUAL_TYPES = {StockMovementType.entrada_ajuste, StockMovementType.saida_ajuste, StockMovementType.perda}


async def _require_view(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "inventory.view")


async def _require_manage(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "inventory.manage")


# ── Schemas ──────────────────────────────────────────────────────────────────


class MovimentacaoOut(BaseModel):
    id: int
    variant_id: int
    variant_name: str
    product_name: str
    movement_type: StockMovementType
    qty_delta: float
    qty_after: float
    reason: Optional[str]
    reference_type: Optional[str]
    reference_id: Optional[int]
    created_at: datetime


class MovimentacaoIn(BaseModel):
    variant_id: int = Field(..., gt=0)
    movement_type: StockMovementType
    qty: Decimal = Field(..., gt=Decimal("0"), description="Quantidade em módulo — o sinal vem do `movement_type`.")
    reason: Optional[str] = Field(None, max_length=500)

    def signed_qty(self) -> Decimal:
        return self.qty if self.movement_type == StockMovementType.entrada_ajuste else -self.qty


class AlertaOut(BaseModel):
    variant_id: int
    variant_name: str
    product_name: str
    stock_qty: float
    min_stock: float


# ── Movimentações ────────────────────────────────────────────────────────────


@router.get("/movimentacoes", response_model=list[MovimentacaoOut])
async def listar_movimentacoes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    variant_id: Optional[int] = Query(None),
    movement_type: Optional[StockMovementType] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[MovimentacaoOut]:
    await _require_view(db, current_user)

    stmt = (
        select(StockMovement, ProductVariant.name, Product.name)
        .join(ProductVariant, ProductVariant.id == StockMovement.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .limit(limit)
    )
    if variant_id is not None:
        stmt = stmt.where(StockMovement.variant_id == variant_id)
    if movement_type is not None:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    if date_from is not None:
        stmt = stmt.where(StockMovement.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(StockMovement.created_at < date_to)

    rows = (await db.execute(stmt)).all()
    return [
        MovimentacaoOut(
            id=m.id,
            variant_id=m.variant_id,
            variant_name=variant_name,
            product_name=product_name,
            movement_type=m.movement_type,
            qty_delta=float(m.qty_delta),
            qty_after=float(m.qty_after),
            reason=m.reason,
            reference_type=m.reference_type,
            reference_id=m.reference_id,
            created_at=m.created_at,
        )
        for m, variant_name, product_name in rows
    ]


@router.post("/movimentacoes", response_model=MovimentacaoOut, status_code=http_status.HTTP_201_CREATED)
async def lancar_movimentacao(
    body: MovimentacaoIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MovimentacaoOut:
    await _require_manage(db, current_user)

    if body.movement_type not in _MANUAL_TYPES:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Só entrada_ajuste/saida_ajuste/perda podem ser lançadas manualmente.",
        )
    if body.movement_type == StockMovementType.perda and not body.reason:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Informe o motivo da perda.")

    variant_row = (
        await db.execute(
            select(ProductVariant, Product.name, Product.tracks_stock)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(ProductVariant.id == body.variant_id)
        )
    ).first()
    if variant_row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Variação não encontrada.")
    variant, product_name, tracks_stock = variant_row
    if not tracks_stock:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Este produto não tem controle de estoque (`tracks_stock=false`).",
        )

    movement = await apply_stock_movement(
        db,
        organization_id=current_user.organization_id,
        variant_id=body.variant_id,
        movement_type=body.movement_type,
        qty_delta=body.signed_qty(),
        reason=body.reason,
        reference_type="manual",
        created_by_user_id=current_user.id,
    )
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="inventory.movement.create",
        resource_type="stock_movement",
        resource_id=movement.id,
        after={
            "variant_id": movement.variant_id,
            "movement_type": movement.movement_type.value,
            "qty_delta": float(movement.qty_delta),
            "reason": movement.reason,
        },
    )
    return MovimentacaoOut(
        id=movement.id,
        variant_id=movement.variant_id,
        variant_name=variant.name,
        product_name=product_name,
        movement_type=movement.movement_type,
        qty_delta=float(movement.qty_delta),
        qty_after=float(movement.qty_after),
        reason=movement.reason,
        reference_type=movement.reference_type,
        reference_id=movement.reference_id,
        created_at=movement.created_at,
    )


# ── Alertas de mínimo ────────────────────────────────────────────────────────


@router.get("/alertas", response_model=list[AlertaOut])
async def listar_alertas(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[AlertaOut]:
    await _require_view(db, current_user)
    return [AlertaOut(**row) for row in await low_stock_alerts(db)]
