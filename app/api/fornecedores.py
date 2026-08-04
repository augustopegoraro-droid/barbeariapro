"""Fornecedores e pedidos de compra — Fase 5 do módulo de Produtos/Estoque/
Vendas (plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

`PurchaseOrder` nasce `rascunho` → `enviar` marca `enviado` → `receber` lança
`stock_movements` tipo `entrada_compra` (via
`app/services/inventory.py::apply_stock_movement`) por item recebido e
recalcula `ProductVariant.cost_avg` por média ponderada
(`(stock_atual*cost_atual + qty_recebida*unit_cost) / (stock_atual+qty_recebida)`),
igual ao plano. Recebimento pode ser parcial (`qty_received` acumula por
item); o status do pedido deriva do total recebido × total pedido.
Cancelar só é permitido antes de qualquer recebimento — depois disso o
estoque já saiu fisicamente errado de reverter automaticamente (ajuste
manual via `/estoque/movimentacoes` cobre esse caso residual).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
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
from app.services.inventory import apply_stock_movement
from models import (
    Product,
    ProductVariant,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    StockMovementType,
    Supplier,
    User,
)

router = APIRouter(tags=["fornecedores"])


async def _require_suppliers_view(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "suppliers.view")


async def _require_suppliers_manage(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "suppliers.manage")


async def _require_purchases_view(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "purchases.view")


async def _require_purchases_manage(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "purchases.manage")


# ── Schemas — fornecedores ────────────────────────────────────────────────────


class FornecedorOut(BaseModel):
    id: int
    name: str
    document: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    notes: Optional[str]
    active: bool

    class Config:
        from_attributes = True


class FornecedorIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    document: Optional[str] = Field(None, max_length=32)
    phone: Optional[str] = Field(None, max_length=32)
    email: Optional[str] = Field(None, max_length=150)
    notes: Optional[str] = Field(None, max_length=2000)


class FornecedorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    document: Optional[str] = Field(None, max_length=32)
    phone: Optional[str] = Field(None, max_length=32)
    email: Optional[str] = Field(None, max_length=150)
    notes: Optional[str] = Field(None, max_length=2000)
    active: Optional[bool] = None


# ── Schemas — pedidos de compra ───────────────────────────────────────────────


class ItemPedidoIn(BaseModel):
    variant_id: int = Field(..., gt=0)
    qty_ordered: Decimal = Field(..., gt=Decimal("0"))
    unit_cost: Decimal = Field(..., ge=Decimal("0"))


class PedidoIn(BaseModel):
    supplier_id: int = Field(..., gt=0)
    expected_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=2000)
    items: list[ItemPedidoIn] = Field(..., min_length=1)


class ItemPedidoOut(BaseModel):
    id: int
    variant_id: int
    variant_name: str
    product_name: str
    qty_ordered: float
    qty_received: float
    unit_cost: float


class PedidoOut(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str
    status: PurchaseOrderStatus
    order_date: date
    expected_date: Optional[date]
    received_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    items: list[ItemPedidoOut]


class PedidoListOut(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str
    status: PurchaseOrderStatus
    order_date: date
    expected_date: Optional[date]
    created_at: datetime
    item_count: int


class ReceberItemIn(BaseModel):
    item_id: int = Field(..., gt=0)
    qty: Decimal = Field(..., gt=Decimal("0"))


class ReceberIn(BaseModel):
    items: list[ReceberItemIn] = Field(..., min_length=1)


def _pedido_item_out(item: PurchaseOrderItem) -> ItemPedidoOut:
    return ItemPedidoOut(
        id=item.id,
        variant_id=item.variant_id,
        variant_name=item.variant.name,
        product_name=item.variant.product.name,
        qty_ordered=float(item.qty_ordered),
        qty_received=float(item.qty_received),
        unit_cost=float(item.unit_cost),
    )


def _pedido_out(po: PurchaseOrder) -> PedidoOut:
    return PedidoOut(
        id=po.id,
        supplier_id=po.supplier_id,
        supplier_name=po.supplier.name,
        status=po.status,
        order_date=po.order_date,
        expected_date=po.expected_date,
        received_at=po.received_at,
        notes=po.notes,
        created_at=po.created_at,
        items=[_pedido_item_out(i) for i in po.items],
    )


async def _load_pedido(db: AsyncSession, po_id: int) -> PurchaseOrder:
    result = await db.execute(
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.items)
            .selectinload(PurchaseOrderItem.variant)
            .selectinload(ProductVariant.product),
        )
        .where(PurchaseOrder.id == po_id)
    )
    po = result.scalar_one_or_none()
    if po is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Pedido de compra não encontrado.")
    return po


# ── Fornecedores ─────────────────────────────────────────────────────────────


@router.get("/fornecedores", response_model=list[FornecedorOut])
async def listar_fornecedores(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    include_inactive: bool = Query(False),
) -> list[FornecedorOut]:
    await _require_suppliers_view(db, current_user)
    stmt = select(Supplier).order_by(Supplier.name)
    if not include_inactive:
        stmt = stmt.where(Supplier.active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [FornecedorOut.model_validate(s) for s in rows]


@router.post("/fornecedores", response_model=FornecedorOut, status_code=http_status.HTTP_201_CREATED)
async def criar_fornecedor(
    body: FornecedorIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> FornecedorOut:
    await _require_suppliers_manage(db, current_user)

    supplier = Supplier(
        organization_id=current_user.organization_id,
        name=body.name,
        document=body.document,
        phone=body.phone,
        email=body.email,
        notes=body.notes,
    )
    db.add(supplier)
    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="suppliers.supplier.create",
        resource_type="supplier",
        resource_id=supplier.id,
        after={"name": supplier.name},
    )
    return FornecedorOut.model_validate(supplier)


@router.patch("/fornecedores/{id}", response_model=FornecedorOut)
async def atualizar_fornecedor(
    body: FornecedorUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> FornecedorOut:
    await _require_suppliers_manage(db, current_user)

    supplier = (
        await db.execute(select(Supplier).where(Supplier.id == id))
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Fornecedor não encontrado.")

    before = {"name": supplier.name, "active": supplier.active}
    if body.name is not None:
        supplier.name = body.name
    if body.document is not None:
        supplier.document = body.document
    if body.phone is not None:
        supplier.phone = body.phone
    if body.email is not None:
        supplier.email = body.email
    if body.notes is not None:
        supplier.notes = body.notes
    if body.active is not None:
        supplier.active = body.active

    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="suppliers.supplier.update",
        resource_type="supplier",
        resource_id=supplier.id,
        before=before,
        after={"name": supplier.name, "active": supplier.active},
    )
    return FornecedorOut.model_validate(supplier)


# ── Pedidos de compra ────────────────────────────────────────────────────────


@router.get("/compras", response_model=list[PedidoListOut])
async def listar_pedidos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    status_filter: Optional[PurchaseOrderStatus] = Query(None, alias="status"),
    supplier_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[PedidoListOut]:
    await _require_purchases_view(db, current_user)

    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.supplier), selectinload(PurchaseOrder.items))
        .order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
        .limit(limit)
    )
    if status_filter is not None:
        stmt = stmt.where(PurchaseOrder.status == status_filter)
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        PedidoListOut(
            id=po.id,
            supplier_id=po.supplier_id,
            supplier_name=po.supplier.name,
            status=po.status,
            order_date=po.order_date,
            expected_date=po.expected_date,
            created_at=po.created_at,
            item_count=len(po.items),
        )
        for po in rows
    ]


@router.post("/compras", response_model=PedidoOut, status_code=http_status.HTTP_201_CREATED)
async def criar_pedido(
    body: PedidoIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PedidoOut:
    await _require_purchases_manage(db, current_user)

    supplier = (
        await db.execute(select(Supplier).where(Supplier.id == body.supplier_id))
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Fornecedor não encontrado.")

    variant_ids = [i.variant_id for i in body.items]
    variant_rows = (
        await db.execute(
            select(ProductVariant.id, Product.tracks_stock)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(ProductVariant.id.in_(variant_ids))
        )
    ).all()
    tracks_stock_by_id = {v_id: tracks for v_id, tracks in variant_rows}
    missing = set(variant_ids) - set(tracks_stock_by_id)
    if missing:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Variação(ões) não encontrada(s): {sorted(missing)}.")
    untracked = [v_id for v_id in variant_ids if not tracks_stock_by_id[v_id]]
    if untracked:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Variação(ões) sem controle de estoque (`tracks_stock=false`), não é possível comprar: {untracked}.",
        )

    po = PurchaseOrder(
        organization_id=current_user.organization_id,
        supplier_id=supplier.id,
        status=PurchaseOrderStatus.rascunho,
        expected_date=body.expected_date,
        notes=body.notes,
        created_by_user_id=current_user.id,
    )
    db.add(po)
    await db.flush()

    for item in body.items:
        db.add(
            PurchaseOrderItem(
                organization_id=current_user.organization_id,
                purchase_order_id=po.id,
                variant_id=item.variant_id,
                qty_ordered=item.qty_ordered,
                unit_cost=item.unit_cost,
            )
        )
    await db.flush()

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="purchases.order.create",
        resource_type="purchase_order",
        resource_id=po.id,
        after={"supplier_id": supplier.id, "items": len(body.items)},
    )
    return _pedido_out(await _load_pedido(db, po.id))


@router.get("/compras/{id}", response_model=PedidoOut)
async def obter_pedido(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> PedidoOut:
    await _require_purchases_view(db, current_user)
    return _pedido_out(await _load_pedido(db, id))


@router.patch("/compras/{id}/enviar", response_model=PedidoOut)
async def enviar_pedido(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> PedidoOut:
    await _require_purchases_manage(db, current_user)

    po = await _load_pedido(db, id)
    if po.status != PurchaseOrderStatus.rascunho:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Só um pedido em rascunho pode ser enviado.")

    po.status = PurchaseOrderStatus.enviado
    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="purchases.order.send",
        resource_type="purchase_order",
        resource_id=po.id,
        before={"status": "rascunho"},
        after={"status": "enviado"},
    )
    return _pedido_out(po)


@router.post("/compras/{id}/receber", response_model=PedidoOut)
async def receber_pedido(
    body: ReceberIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> PedidoOut:
    await _require_purchases_manage(db, current_user)

    po = await _load_pedido(db, id)
    if po.status not in (PurchaseOrderStatus.enviado, PurchaseOrderStatus.recebido_parcial):
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Só é possível receber um pedido enviado ou parcialmente recebido.",
        )

    items_by_id = {i.id: i for i in po.items}
    missing = [b.item_id for b in body.items if b.item_id not in items_by_id]
    if missing:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Item(ns) do pedido não encontrado(s): {missing}.")

    for received in body.items:
        item = items_by_id[received.item_id]
        remaining = item.qty_ordered - item.qty_received
        if received.qty > remaining:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Item {item.id}: quantidade recebida ({received.qty}) maior que o restante pedido ({remaining}).",
            )

        variant = (
            await db.execute(
                select(ProductVariant)
                .where(ProductVariant.id == item.variant_id)
                .with_for_update(of=ProductVariant)
            )
        ).scalar_one_or_none()
        if variant is None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Variação não encontrada.")

        old_qty = variant.stock_qty
        old_cost = variant.cost_avg
        new_qty_total = old_qty + received.qty
        new_cost_avg = (
            ((old_qty * old_cost) + (received.qty * item.unit_cost)) / new_qty_total
            if new_qty_total > 0
            else old_cost
        )
        variant.cost_avg = new_cost_avg.quantize(Decimal("0.01"))

        item.qty_received = item.qty_received + received.qty

        await apply_stock_movement(
            db,
            organization_id=current_user.organization_id,
            variant_id=variant.id,
            movement_type=StockMovementType.entrada_compra,
            qty_delta=received.qty,
            unit_cost=item.unit_cost,
            reference_type="purchase_order",
            reference_id=po.id,
            created_by_user_id=current_user.id,
        )

    all_received = all(i.qty_received >= i.qty_ordered for i in po.items)
    po.status = PurchaseOrderStatus.recebido if all_received else PurchaseOrderStatus.recebido_parcial
    if all_received:
        po.received_at = datetime.now(timezone.utc)

    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="purchases.order.receive",
        resource_type="purchase_order",
        resource_id=po.id,
        after={"status": po.status.value, "items_received": len(body.items)},
    )
    return _pedido_out(await _load_pedido(db, po.id))


@router.patch("/compras/{id}/cancelar", response_model=PedidoOut)
async def cancelar_pedido(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> PedidoOut:
    await _require_purchases_manage(db, current_user)

    po = await _load_pedido(db, id)
    if po.status not in (PurchaseOrderStatus.rascunho, PurchaseOrderStatus.enviado):
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Só é possível cancelar um pedido sem nenhum recebimento (rascunho ou enviado).",
        )

    po.status = PurchaseOrderStatus.cancelado
    await db.flush()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="purchases.order.cancel",
        resource_type="purchase_order",
        resource_id=po.id,
        after={"status": "cancelado"},
    )
    return _pedido_out(po)
