"""Estoque — Fases 2 e 6 do módulo de Produtos/Estoque/Vendas (plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Fase 2: entrada/saída de mercadoria via ajuste manual (sem depender de
Compras, que é Fase 5) + alertas de mínimo. Baixa automática por venda fica
para a Fase 3 (`sales`).

Fase 6: contagem física de estoque (`inventory_counts`/
`inventory_count_items`) — operação periódica, não do dia a dia. Abrir uma
contagem congela `stock_qty` corrente de cada variação rastreada/ativa em
`expected_qty`; a Raquel preenche `counted_qty` por item; finalizar gera
`stock_movements` tipo `inventario` só para os itens divergentes, via
`app/services/inventory.py::finalize_inventory_count` (nunca escreve
`stock_qty` diretamente aqui).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.services.audit import record_event
from app.services.inventory import apply_stock_movement, finalize_inventory_count, low_stock_alerts
from app.services.management import stock_turnover
from models import (
    InventoryCount,
    InventoryCountItem,
    InventoryCountStatus,
    Product,
    ProductVariant,
    StockMovement,
    StockMovementType,
    User,
)

router = APIRouter(prefix="/estoque", tags=["estoque"])

_MANUAL_TYPES = {StockMovementType.entrada_ajuste, StockMovementType.saida_ajuste, StockMovementType.perda}


async def _require_view(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "inventory.view")


async def _require_manage(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "inventory.manage")


async def _require_count_manage(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "inventory.count.manage")


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


class InventoryCountItemOut(BaseModel):
    id: int
    variant_id: int
    variant_name: str
    product_name: str
    expected_qty: float
    counted_qty: Optional[float]


class InventoryCountOut(BaseModel):
    id: int
    status: InventoryCountStatus
    started_at: datetime
    finalized_at: Optional[datetime]
    items: list[InventoryCountItemOut]


class InventoryCountListOut(BaseModel):
    id: int
    status: InventoryCountStatus
    started_at: datetime
    finalized_at: Optional[datetime]
    item_count: int


class ContagemItemIn(BaseModel):
    counted_qty: Decimal = Field(..., ge=Decimal("0"))


class GiroEstoqueOut(BaseModel):
    variant_id: int
    variant_name: str
    product_name: str
    qty_sold: float
    avg_stock: float
    turnover: Optional[float]


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


# ── Giro de estoque (Fase 7) ─────────────────────────────────────────────────


@router.get("/giro", response_model=list[GiroEstoqueOut])
async def listar_giro(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> list[GiroEstoqueOut]:
    await _require_view(db, current_user)
    rows = await stock_turnover(db, date_from, date_to)
    return [GiroEstoqueOut(**row) for row in rows]


# ── Inventário / contagem física (Fase 6) ───────────────────────────────────


async def _load_count(db: AsyncSession, count_id: int) -> InventoryCount:
    result = await db.execute(
        select(InventoryCount)
        .options(
            selectinload(InventoryCount.items)
            .selectinload(InventoryCountItem.variant)
            .selectinload(ProductVariant.product)
        )
        .where(InventoryCount.id == count_id)
    )
    count = result.scalar_one_or_none()
    if count is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Contagem não encontrada.")
    return count


def _count_out(count: InventoryCount) -> InventoryCountOut:
    return InventoryCountOut(
        id=count.id,
        status=count.status,
        started_at=count.started_at,
        finalized_at=count.finalized_at,
        items=[
            InventoryCountItemOut(
                id=item.id,
                variant_id=item.variant_id,
                variant_name=item.variant.name,
                product_name=item.variant.product.name,
                expected_qty=float(item.expected_qty),
                counted_qty=float(item.counted_qty) if item.counted_qty is not None else None,
            )
            for item in count.items
        ],
    )


@router.get("/inventarios", response_model=list[InventoryCountListOut])
async def listar_inventarios(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[InventoryCountListOut]:
    await _require_view(db, current_user)
    rows = (
        await db.execute(
            select(InventoryCount)
            .options(selectinload(InventoryCount.items))
            .order_by(InventoryCount.started_at.desc(), InventoryCount.id.desc())
        )
    ).scalars().all()
    return [
        InventoryCountListOut(
            id=c.id,
            status=c.status,
            started_at=c.started_at,
            finalized_at=c.finalized_at,
            item_count=len(c.items),
        )
        for c in rows
    ]


@router.get("/inventarios/{id}", response_model=InventoryCountOut)
async def obter_inventario(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> InventoryCountOut:
    await _require_view(db, current_user)
    return _count_out(await _load_count(db, id))


@router.post("/inventarios", response_model=InventoryCountOut, status_code=http_status.HTTP_201_CREATED)
async def abrir_inventario(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> InventoryCountOut:
    """Abre uma contagem congelando `stock_qty` de toda variação
    rastreada/ativa em `expected_qty`. Não há filtro de categoria/produto
    nesta fase — a contagem cobre o cardápio inteiro rastreado."""
    await _require_count_manage(db, current_user)

    variant_rows = (
        await db.execute(
            select(ProductVariant.id, ProductVariant.stock_qty)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(Product.tracks_stock.is_(True))
            .where(ProductVariant.active.is_(True))
            .where(Product.active.is_(True))
        )
    ).all()
    if not variant_rows:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT, "Nenhuma variação com controle de estoque para contar."
        )

    count = InventoryCount(
        organization_id=current_user.organization_id,
        status=InventoryCountStatus.aberto,
        created_by_user_id=current_user.id,
    )
    db.add(count)
    await db.flush()

    for variant_id, stock_qty in variant_rows:
        db.add(
            InventoryCountItem(
                organization_id=current_user.organization_id,
                inventory_count_id=count.id,
                variant_id=variant_id,
                expected_qty=stock_qty,
            )
        )
    await db.flush()

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="inventory.count.open",
        resource_type="inventory_count",
        resource_id=count.id,
        after={"item_count": len(variant_rows)},
    )
    return _count_out(await _load_count(db, count.id))


@router.patch("/inventarios/{id}/itens/{item_id}", response_model=InventoryCountOut)
async def informar_contagem(
    body: ContagemItemIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
    item_id: int = Path(..., gt=0),
) -> InventoryCountOut:
    await _require_count_manage(db, current_user)

    count = await _load_count(db, id)
    if count.status != InventoryCountStatus.aberto:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Contagem já finalizada.")

    item = next((i for i in count.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Item da contagem não encontrado.")

    item.counted_qty = body.counted_qty
    await db.flush()
    return _count_out(await _load_count(db, id))


@router.post("/inventarios/{id}/finalizar", response_model=InventoryCountOut)
async def finalizar_inventario(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> InventoryCountOut:
    await _require_count_manage(db, current_user)

    count = await _load_count(db, id)
    if count.status != InventoryCountStatus.aberto:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Contagem já finalizada.")

    divergent = [
        {
            "variant_id": item.variant_id,
            "expected_qty": float(item.expected_qty),
            "counted_qty": float(item.counted_qty),
        }
        for item in count.items
        if item.counted_qty is not None and item.counted_qty != item.expected_qty
    ]

    await finalize_inventory_count(
        db,
        organization_id=current_user.organization_id,
        count=count,
        created_by_user_id=current_user.id,
    )

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="inventory.count.finalize",
        resource_type="inventory_count",
        resource_id=count.id,
        after={"divergent_items": divergent},
    )
    return _count_out(await _load_count(db, id))
