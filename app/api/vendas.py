"""Venda de produtos — Fase 3 do módulo de Produtos/Estoque/Vendas (plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Venda de balcão (sem agendamento) ou anexada a um atendimento
(`appointment_id` preenchido, sem tocar em `AppointmentItem`/`Payment`).
A baixa de estoque é síncrona, na mesma transação da venda
(`app/services/inventory.py::apply_stock_movement`, tipo `saida_venda`) —
produtos sem `tracks_stock` não geram movimentação. Cancelar reverte o
estoque (tipo `saida_ajuste` com quantidade positiva) e marca
`status="cancelada"`, nunca apaga linha.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.services import cash_register as cash
from app.services.audit import record_event
from app.services.inventory import apply_stock_movement
from app.services.management import top_selling_products
from models import (
    CashMovement,
    CashMovementType,
    Client,
    Product,
    ProductVariant,
    PaymentMethod,
    Sale,
    SaleItem,
    SalePayment,
    SaleStatus,
    StockMovementType,
    Unit,
    User,
)

router = APIRouter(prefix="/vendas", tags=["vendas"])


async def _require_view(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "sales.view")


async def _require_create(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "sales.create")


async def _require_cancel(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "sales.cancel")


# ── Schemas ──────────────────────────────────────────────────────────────────


class ItemIn(BaseModel):
    variant_id: int = Field(..., gt=0)
    qty: Decimal = Field(..., gt=Decimal("0"))


class PagamentoIn(BaseModel):
    amount: Decimal = Field(..., gt=Decimal("0"))
    method: PaymentMethod


class VendaIn(BaseModel):
    client_id: Optional[int] = None
    appointment_id: Optional[int] = None
    items: list[ItemIn] = Field(..., min_length=1)
    payments: list[PagamentoIn] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _sem_variantes_repetidas(self) -> "VendaIn":
        variant_ids = [item.variant_id for item in self.items]
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError("Cada variação só pode aparecer uma vez por venda — some as quantidades.")
        return self


class ItemOut(BaseModel):
    id: int
    variant_id: int
    variant_name: str
    product_name: str
    qty: float
    unit_price_charged: float
    unit_cost_snapshot: float


class PagamentoOut(BaseModel):
    id: int
    amount: float
    method: PaymentMethod
    paid_at: datetime


class VendaOut(BaseModel):
    id: int
    status: SaleStatus
    client_id: Optional[int]
    client_name: Optional[str]
    appointment_id: Optional[int]
    total_amount: float
    created_at: datetime
    items: list[ItemOut]
    payments: list[PagamentoOut]


class VendaListOut(BaseModel):
    id: int
    status: SaleStatus
    client_id: Optional[int]
    client_name: Optional[str]
    appointment_id: Optional[int]
    total_amount: float
    created_at: datetime


class ProdutoMaisVendidoOut(BaseModel):
    variant_id: int
    variant_name: str
    product_name: str
    price: float
    qty_sold: float
    revenue: float


async def _load_sale(db: AsyncSession, sale_id: int) -> Sale:
    result = await db.execute(
        select(Sale)
        .options(
            selectinload(Sale.items).selectinload(SaleItem.variant).selectinload(ProductVariant.product),
            selectinload(Sale.payments),
            selectinload(Sale.client),
        )
        .where(Sale.id == sale_id)
    )
    sale = result.scalar_one_or_none()
    if sale is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Venda não encontrada.")
    return sale


def _venda_out(sale: Sale) -> VendaOut:
    return VendaOut(
        id=sale.id,
        status=sale.status,
        client_id=sale.client_id,
        client_name=sale.client.name if sale.client else None,
        appointment_id=sale.appointment_id,
        total_amount=float(sale.total_amount),
        created_at=sale.created_at,
        items=[
            ItemOut(
                id=item.id,
                variant_id=item.variant_id,
                variant_name=item.variant.name,
                product_name=item.variant.product.name,
                qty=float(item.qty),
                unit_price_charged=float(item.unit_price_charged),
                unit_cost_snapshot=float(item.unit_cost_snapshot),
            )
            for item in sale.items
        ],
        payments=[
            PagamentoOut(id=p.id, amount=float(p.amount), method=p.method, paid_at=p.paid_at)
            for p in sale.payments
        ],
    )


# ── Vendas ───────────────────────────────────────────────────────────────────


@router.get("", response_model=list[VendaListOut])
async def listar_vendas(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    status_filter: Optional[SaleStatus] = Query(None, alias="status"),
    client_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[VendaListOut]:
    await _require_view(db, current_user)

    stmt = (
        select(Sale)
        .options(selectinload(Sale.client))
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(limit)
    )
    if status_filter is not None:
        stmt = stmt.where(Sale.status == status_filter)
    if client_id is not None:
        stmt = stmt.where(Sale.client_id == client_id)
    if date_from is not None:
        stmt = stmt.where(Sale.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Sale.created_at < date_to)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        VendaListOut(
            id=s.id,
            status=s.status,
            client_id=s.client_id,
            client_name=s.client.name if s.client else None,
            appointment_id=s.appointment_id,
            total_amount=float(s.total_amount),
            created_at=s.created_at,
        )
        for s in rows
    ]


@router.get("/produtos-mais-vendidos", response_model=list[ProdutoMaisVendidoOut])
async def produtos_mais_vendidos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(10, ge=1, le=50),
    only_active: bool = Query(
        False, description="Descarta produto/variação arquivados (atalhos de venda)"
    ),
) -> list[ProdutoMaisVendidoOut]:
    """Relatório de produtos mais vendidos no período (Fase 7). Com
    `only_active=true`, alimenta os botões de acesso rápido da conclusão de
    atendimento."""
    await _require_view(db, current_user)
    rows = await top_selling_products(
        db, date_from, date_to, limit=limit, only_active=only_active
    )
    return [ProdutoMaisVendidoOut(**row) for row in rows]


@router.get("/{id}", response_model=VendaOut)
async def obter_venda(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> VendaOut:
    await _require_view(db, current_user)
    return _venda_out(await _load_sale(db, id))


@router.post("", response_model=VendaOut, status_code=http_status.HTTP_201_CREATED)
async def criar_venda(
    body: VendaIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> VendaOut:
    await _require_create(db, current_user)

    if body.client_id is not None:
        client = (
            await db.execute(select(Client).where(Client.id == body.client_id))
        ).scalar_one_or_none()
        if client is None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    payments_total = sum(p.amount for p in body.payments)

    variant_rows = (
        await db.execute(
            select(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(ProductVariant.id.in_([i.variant_id for i in body.items]))
        )
    ).all()
    variants_by_id = {v.id: (v, p) for v, p in variant_rows}

    missing = [i.variant_id for i in body.items if i.variant_id not in variants_by_id]
    if missing:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Variação(ões) não encontrada(s): {missing}.")

    total_amount = sum(
        variants_by_id[i.variant_id][0].price * i.qty for i in body.items
    ).quantize(Decimal("0.01"))
    if payments_total != total_amount:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Soma dos pagamentos (R$ {payments_total}) não bate com o total da venda (R$ {total_amount}).",
        )

    unit = (
        await db.execute(select(Unit).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1))
    ).scalar_one_or_none()
    if unit is None:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Organização sem unidade cadastrada.")

    # Caixa vivo (D-101): venda paga (parte) em DINHEIRO exige caixa aberto
    # quando o enforcement da org está ligado. Checa ANTES de gravar.
    cash_amount = sum(
        (p.amount for p in body.payments if p.method == PaymentMethod.dinheiro), Decimal("0")
    )
    cash_session = None
    if cash_amount > 0:
        cash_session = await cash.require_open_session(
            db, organization_id=current_user.organization_id, unit_id=unit.id
        )

    sale = Sale(
        organization_id=current_user.organization_id,
        unit_id=unit.id,
        client_id=body.client_id,
        appointment_id=body.appointment_id,
        status=SaleStatus.concluida,
        total_amount=total_amount,
        created_by_user_id=current_user.id,
    )
    db.add(sale)
    await db.flush()

    for item in body.items:
        variant, product = variants_by_id[item.variant_id]
        db.add(
            SaleItem(
                organization_id=current_user.organization_id,
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
                organization_id=current_user.organization_id,
                variant_id=variant.id,
                movement_type=StockMovementType.saida_venda,
                qty_delta=-item.qty,
                reference_type="sale",
                reference_id=sale.id,
                created_by_user_id=current_user.id,
            )

    for payment in body.payments:
        db.add(
            SalePayment(
                organization_id=current_user.organization_id,
                sale_id=sale.id,
                amount=payment.amount,
                method=payment.method,
            )
        )
    await db.flush()

    if cash_session is not None:
        await cash.post_movement(
            db,
            cash_session,
            type=CashMovementType.venda_produto,
            amount=cash_amount,
            reference_type="sale",
            reference_id=sale.id,
            user_id=current_user.id,
        )

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="sales.sale.create",
        resource_type="sale",
        resource_id=sale.id,
        after={
            "total_amount": float(sale.total_amount),
            "items": len(body.items),
            "appointment_id": sale.appointment_id,
            "client_id": sale.client_id,
        },
    )
    return _venda_out(await _load_sale(db, sale.id))


@router.patch("/{id}/cancelar", response_model=VendaOut)
async def cancelar_venda(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    id: int = Path(..., gt=0),
) -> VendaOut:
    await _require_cancel(db, current_user)

    sale = await _load_sale(db, id)
    if sale.status != SaleStatus.concluida:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Só é possível cancelar uma venda concluída.")

    for item in sale.items:
        if item.variant.product.tracks_stock:
            await apply_stock_movement(
                db,
                organization_id=current_user.organization_id,
                variant_id=item.variant_id,
                movement_type=StockMovementType.saida_ajuste,
                qty_delta=item.qty,
                reason="Estorno de venda cancelada",
                reference_type="sale",
                reference_id=sale.id,
                created_by_user_id=current_user.id,
            )

    sale.status = SaleStatus.cancelada
    await db.flush()

    # Caixa vivo (D-101): se a venda tinha dinheiro lançado no caixa, estorna
    # com um `ajuste` negativo NO CAIXA ABERTO ATUAL (não no turno original).
    # Sem caixa aberto, apenas registra em log — cancelar nunca é bloqueado.
    cash_mov = (
        await db.execute(
            select(CashMovement)
            .where(CashMovement.reference_type == "sale")
            .where(CashMovement.reference_id == sale.id)
        )
    ).scalar_one_or_none()
    if cash_mov is not None:
        open_session = await cash.get_open_session(db, sale.unit_id)
        if open_session is not None:
            await cash.post_movement(
                db,
                open_session,
                type=CashMovementType.ajuste,
                amount=-cash_mov.amount,
                reference_type="sale_cancel",
                reference_id=sale.id,
                note="Estorno de venda cancelada",
                user_id=current_user.id,
            )

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="sales.sale.cancel",
        resource_type="sale",
        resource_id=sale.id,
        before={"status": "concluida"},
        after={"status": "cancelada"},
    )
    return _venda_out(await _load_sale(db, sale.id))
