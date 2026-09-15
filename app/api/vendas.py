"""Venda de produtos — Fase 3 do módulo de Produtos/Estoque/Vendas (plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md),
remodelada pelo checkout único (D-105,
/Users/apleandro/.claude/plans/magical-forging-iverson.md): produto vendido
junto de um atendimento SÓ fecha quando o atendimento fecha (a Sale nasce
dentro de `app/api/barbeiro.py::concluir_atendimento`, nunca antes). Quem só
quer comprar um produto, sem atendimento, passa por `POST /vendas/balcao`
(cria+conclui um atendimento "Balcão" mínimo na mesma chamada). `POST /vendas`
segue existindo para compatibilidade/API direta, mas a UI não chama mais para
venda de balcão avulsa.

A baixa de estoque é síncrona, na mesma transação da venda
(`app/services/inventory.py::apply_stock_movement`, tipo `saida_venda`) —
produtos sem `tracks_stock` não geram movimentação. Cancelar reverte o
estoque (tipo `saida_ajuste` com quantidade positiva) e marca
`status="cancelada"`, nunca apaga linha.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.services import cash_register as cash
from app.services import client_wallet
from app.services.audit import record_event
from app.services.inventory import apply_stock_movement
from app.services.management import top_selling_products
from app.services.sales import SaleItemIn, build_sale
from models import (
    Appointment,
    AppointmentItem,
    Barber,
    CardBrand,
    CardType,
    CashMovement,
    CashMovementType,
    Client,
    ProductVariant,
    PaymentMethod,
    Sale,
    SaleItem,
    SalePayment,
    SaleStatus,
    Service,
    ServiceCategory,
    StockMovementType,
    Unit,
    User,
    UserUnit,
)
from models.enums import AppointmentStatus

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
    card_type: Optional[CardType] = None
    card_brand: Optional[CardBrand] = None

    @model_validator(mode="after")
    def _cartao_exige_bandeira(self) -> "PagamentoIn":
        if self.method == PaymentMethod.cartao:
            if self.card_type is None or self.card_brand is None:
                raise ValueError("Pagamento em cartão exige tipo (crédito/débito) e bandeira.")
        elif self.card_type is not None or self.card_brand is not None:
            raise ValueError("Tipo/bandeira de cartão só se aplicam a pagamento em cartão.")
        return self


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
    card_type: Optional[CardType] = None
    card_brand: Optional[CardBrand] = None
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
            PagamentoOut(
                id=p.id,
                amount=float(p.amount),
                method=p.method,
                card_type=p.card_type,
                card_brand=p.card_brand,
                paid_at=p.paid_at,
            )
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

    payments_total = sum(p.amount for p in body.payments).quantize(Decimal("0.01"))

    unit = (
        await db.execute(select(Unit).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1))
    ).scalar_one_or_none()
    if unit is None:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Organização sem unidade cadastrada.")

    sale = await build_sale(
        db,
        organization_id=current_user.organization_id,
        unit_id=unit.id,
        client_id=body.client_id,
        appointment_id=body.appointment_id,
        items=[SaleItemIn(variant_id=i.variant_id, qty=i.qty) for i in body.items],
        created_by_user_id=current_user.id,
    )
    if payments_total != sale.total_amount:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Soma dos pagamentos (R$ {payments_total}) não bate com o total da venda (R$ {sale.total_amount}).",
        )

    for payment in body.payments:
        db.add(
            SalePayment(
                organization_id=current_user.organization_id,
                sale_id=sale.id,
                amount=payment.amount,
                method=payment.method,
                card_type=payment.card_type,
                card_brand=payment.card_brand,
            )
        )
    await db.flush()

    wallet_used = sum(
        (p.amount for p in body.payments if p.method == PaymentMethod.credito_cliente), Decimal("0")
    )
    if wallet_used > 0:
        if body.client_id is None:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Pagamento com saldo da carteira exige um cliente identificado.",
            )
        await client_wallet.debit(
            db,
            organization_id=current_user.organization_id,
            client_id=body.client_id,
            amount=wallet_used,
            reference_type="sale",
            reference_id=sale.id,
            created_by_user_id=current_user.id,
        )

    # Caixa vivo (D-101): soma só as linhas em DINHEIRO. Cartão/Pix/carteira
    # nunca tocam no caixa.
    await cash.resolve_and_post_cash(
        db,
        [(p.amount, p.method) for p in body.payments],
        organization_id=current_user.organization_id,
        unit_id=unit.id,
        reference_type="sale",
        reference_id=sale.id,
        movement_type=CashMovementType.venda_produto,
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

    # Carteira de crédito do cliente (D-105): devolve o que esta venda
    # especificamente consumiu do saldo (soma das linhas credito_cliente desta
    # Sale — não tenta "desfazer" o débito original por referência, que pode
    # ter sido um lançamento combinado com o serviço no checkout único).
    wallet_used = sum(
        (p.amount for p in sale.payments if p.method == PaymentMethod.credito_cliente), Decimal("0")
    )
    if wallet_used > 0 and sale.client_id is not None:
        await client_wallet.refund(
            db,
            organization_id=current_user.organization_id,
            client_id=sale.client_id,
            amount=wallet_used,
            reference_type="sale_cancel",
            reference_id=sale.id,
            created_by_user_id=current_user.id,
        )

    # Caixa vivo (D-101): se a venda tinha dinheiro lançado no caixa, estorna
    # com um `ajuste` negativo NO CAIXA ABERTO ATUAL (não no turno original).
    # Sem caixa aberto, apenas registra em log — cancelar nunca é bloqueado.
    # Nota: uma venda nascida do checkout único (produto+serviço juntos, D-105)
    # tem seu dinheiro lançado sob reference_type="appointment" (movimento
    # combinado) — este lookup só encontra/estorna o movimento de vendas
    # criadas isoladamente por este router (reference_type="sale"). Cancelar
    # o produto de um checkout combinado não reabre a gaveta sozinho; o
    # gestor corrige via ajuste manual do caixa se necessário.
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


# ── Venda de balcão (D-105) ─────────────────────────────────────────────────
# "Produto sempre amarrado a atendimento": quem só quer levar um produto, sem
# cortar cabelo, ainda fecha através de um atendimento — um "Balcão" mínimo
# criado e concluído nesta mesma chamada, atomicamente, reaproveitando o
# mesmo split/carteira/caixa do checkout único de `app/api/barbeiro.py`.

_BALCAO_SERVICE_NAME = "Balcão (venda de produto)"


async def _get_or_create_balcao_service(db: AsyncSession, organization_id: int) -> Service:
    service = (
        await db.execute(
            select(Service).where(
                Service.organization_id == organization_id,
                Service.name == _BALCAO_SERVICE_NAME,
            )
        )
    ).scalar_one_or_none()
    if service is not None:
        return service
    service = Service(
        organization_id=organization_id,
        name=_BALCAO_SERVICE_NAME,
        category=ServiceCategory.estetica,
        default_duration_min=1,
        price=Decimal("0"),
        cost=Decimal("0"),
    )
    db.add(service)
    await db.flush()
    return service


async def _resolve_walkin_barber_id(db: AsyncSession, *, organization_id: int, user_id: int) -> int:
    linked = (
        await db.execute(
            select(UserUnit.barber_id).where(
                UserUnit.user_id == user_id, UserUnit.barber_id.is_not(None)
            )
        )
    ).scalar_one_or_none()
    if linked is not None:
        return linked
    fallback = (
        await db.execute(
            select(Barber.id)
            .where(Barber.organization_id == organization_id, Barber.deleted_at.is_(None))
            .order_by(Barber.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if fallback is None:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Nenhum profissional cadastrado para registrar a venda.")
    return fallback


class BalcaoIn(BaseModel):
    client_id: int = Field(..., gt=0)
    items: list[ItemIn] = Field(..., min_length=1)
    payments: list[PagamentoIn] = Field(..., min_length=1)


@router.post("/balcao", response_model=VendaOut, status_code=http_status.HTTP_201_CREATED)
async def venda_balcao(
    body: BalcaoIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> VendaOut:
    """Cliente que só quer comprar um produto, sem atendimento agendado:
    cria + conclui um atendimento "Balcão" mínimo (preço/duração 0) e, na
    mesma transação, registra a venda — mesma porta única de estoque/caixa/
    carteira do checkout único."""
    await _require_create(db, current_user)

    client = (
        await db.execute(select(Client).where(Client.id == body.client_id))
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    unit = (
        await db.execute(select(Unit).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1))
    ).scalar_one_or_none()
    if unit is None:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Organização sem unidade cadastrada.")

    service = await _get_or_create_balcao_service(db, current_user.organization_id)
    barber_id = await _resolve_walkin_barber_id(
        db, organization_id=current_user.organization_id, user_id=current_user.id
    )

    await db.execute(text("SELECT pg_advisory_xact_lock(:unit_id)"), {"unit_id": unit.id})
    next_num = (
        await db.execute(
            select(func.coalesce(func.max(Appointment.display_number), 0) + 1).where(
                Appointment.unit_id == unit.id
            )
        )
    ).scalar_one()

    now = datetime.now(timezone.utc)
    appt = Appointment(
        organization_id=current_user.organization_id,
        unit_id=unit.id,
        client_id=client.id,
        display_number=next_num,
        start_at=now,
        end_at=now + timedelta(minutes=1),
        status=AppointmentStatus.concluido,
        total_amount=Decimal("0"),
        created_by_user_id=current_user.id,
    )
    db.add(appt)
    await db.flush()
    db.add(
        AppointmentItem(
            organization_id=current_user.organization_id,
            appointment_id=appt.id,
            service_id=service.id,
            barber_id=barber_id,
            price_charged=Decimal("0"),
            duration_minutes=1,
        )
    )

    sale = await build_sale(
        db,
        organization_id=current_user.organization_id,
        unit_id=unit.id,
        client_id=client.id,
        appointment_id=appt.id,
        items=[SaleItemIn(variant_id=i.variant_id, qty=i.qty) for i in body.items],
        created_by_user_id=current_user.id,
    )

    payments_total = sum(p.amount for p in body.payments).quantize(Decimal("0.01"))
    if payments_total != sale.total_amount:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Soma dos pagamentos (R$ {payments_total}) não bate com o total da venda (R$ {sale.total_amount}).",
        )

    for payment in body.payments:
        db.add(
            SalePayment(
                organization_id=current_user.organization_id,
                sale_id=sale.id,
                amount=payment.amount,
                method=payment.method,
                card_type=payment.card_type,
                card_brand=payment.card_brand,
            )
        )
    await db.flush()

    wallet_used = sum(
        (p.amount for p in body.payments if p.method == PaymentMethod.credito_cliente), Decimal("0")
    )
    if wallet_used > 0:
        await client_wallet.debit(
            db,
            organization_id=current_user.organization_id,
            client_id=client.id,
            amount=wallet_used,
            reference_type="sale",
            reference_id=sale.id,
            created_by_user_id=current_user.id,
        )

    await cash.resolve_and_post_cash(
        db,
        [(p.amount, p.method) for p in body.payments],
        organization_id=current_user.organization_id,
        unit_id=unit.id,
        reference_type="sale",
        reference_id=sale.id,
        movement_type=CashMovementType.venda_produto,
        user_id=current_user.id,
    )

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="sales.sale.create",
        resource_type="sale",
        resource_id=sale.id,
        after={"total_amount": float(sale.total_amount), "items": len(body.items), "channel": "balcao"},
    )
    return _venda_out(await _load_sale(db, sale.id))
