"""Módulo do Barbeiro — ações sobre atendimentos do próprio barbeiro."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status as http_status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import check_appointment_ownership
from app.deps import get_current_user, get_tenant_db, resolve_current_role_with_barber
from app.services import cash_register as cash
from app.services import client_wallet
from app.services.audit import record_event
from app.services.calendar_sync import push_appointment
from app.services.checkout import PaymentLineIn, allocate_payments
from app.services.loyalty import (
    recalculate as _recalculate_loyalty,
    reverse_appointment_points as _reverse_loyalty_points,
)
from app.services.membership import (
    apply_membership_to_appointment,
    resolve_membership_for_autopick,
    revert_usage,
    usage_for_appointment,
)
from app.services.sales import SaleItemIn, build_sale
from models import (
    Appointment,
    AppointmentItem,
    CardBrand,
    CardType,
    CashMovementType,
    ClientMembership,
    Payment,
    SalePayment,
    User,
)
from models.enums import AppointmentStatus, PaymentMethod

router = APIRouter(prefix="/barbeiro", tags=["barbeiro"])


async def _load_appointment(db: AsyncSession, appt_id: int) -> Appointment:
    # FOR UPDATE: serializa transições de status concorrentes sobre o MESMO
    # agendamento (duplo clique/retry da recepção). Sem isso, duas conclusões
    # simultâneas no fluxo em dinheiro passam ambas no _require_agendado (TOCTOU)
    # e criam Payment em dobro — a tabela payments não tem unicidade por
    # agendamento. O lock é só nesta linha, dentro da transação do request.
    row = (
        await db.execute(
            select(Appointment)
            .where(Appointment.id == appt_id)
            .options(selectinload(Appointment.items))
            .with_for_update(of=Appointment)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Agendamento não encontrado.")
    return row


def _require_agendado(appt: Appointment) -> None:
    if appt.status != AppointmentStatus.agendado:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Atendimento já está '{appt.status.value}'. Só é possível atualizar agendamentos com status 'agendado'.",
        )


# ─── schemas ─────────────────────────────────────────────────────────────────

class PagamentoIn(BaseModel):
    """1 linha do split de pagamento. Bandeira/tipo só em `method=cartao`."""

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


class ProdutoItemIn(BaseModel):
    variant_id: int = Field(..., gt=0)
    qty: Decimal = Field(..., gt=Decimal("0"))


class ConcluirRequest(BaseModel):
    # Checkout único: o split cobre serviço + produtos + gorjeta juntos.
    payments: list[PagamentoIn] = Field(default_factory=list)
    # Produtos vendidos junto deste atendimento — a Sale só nasce (e fecha)
    # aqui, na conclusão, nunca antes (D-105).
    produtos: list[ProdutoItemIn] = Field(default_factory=list)
    # Valor cobrado pelo SERVIÇO (sem produtos/gorjeta). Obrigatório quando o
    # atendimento não é pago por assinatura.
    service_amount: Optional[Decimal] = Field(None, ge=0, description="Valor cobrado pelo serviço")
    tip_amount: Optional[Decimal] = Field(None, ge=0, description="Gorjeta (opcional)")
    # Pagar este atendimento com a assinatura do cliente (baixa 1 uso). None =
    # resolve a assinatura ativa do cliente. Atômico com a conclusão.
    membership_id: Optional[int] = Field(None, gt=0)
    usar_assinatura: Optional[bool] = Field(
        None, description="true → paga com a assinatura ativa do cliente"
    )


class AtendimentoOut(BaseModel):
    id: int
    status: str
    total_amount: float


# ─── endpoints ───────────────────────────────────────────────────────────────

@router.patch("/atendimento/{appt_id}/concluir", response_model=AtendimentoOut)
async def concluir_atendimento(
    appt_id: Annotated[int, Path(gt=0)],
    body: ConcluirRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AtendimentoOut:
    role, my_barber_id = await resolve_current_role_with_barber(db, current_user)

    appt = await _load_appointment(db, appt_id)
    check_appointment_ownership(appt, role, my_barber_id)
    _require_agendado(appt)

    # Checkout pago com assinatura: anexa o uso ANTES (atômico com a conclusão);
    # o fluxo abaixo então detecta o usage e trata o serviço como já quitado.
    if (
        body.membership_id is not None or body.usar_assinatura
    ) and await usage_for_appointment(db, appt_id) is None:
        if body.membership_id is not None:
            membership = (
                await db.execute(
                    select(ClientMembership).where(
                        ClientMembership.id == body.membership_id
                    )
                )
            ).scalar_one_or_none()
            if membership is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail="Assinatura não encontrada.",
                )
        else:
            membership = await resolve_membership_for_autopick(db, appt.client_id)
        await apply_membership_to_appointment(
            db, appointment=appt, membership=membership, created_by_user_id=current_user.id
        )

    usage = await usage_for_appointment(db, appt_id)
    paid_by_membership = usage is not None

    if not paid_by_membership and body.service_amount is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o valor cobrado pelo serviço (service_amount).",
        )
    service_total = Decimal("0") if paid_by_membership else Decimal(str(body.service_amount))
    tip_total = Decimal(str(body.tip_amount)) if body.tip_amount else Decimal("0")

    # Produtos vendidos junto — a Sale nasce (e fecha) só aqui, atomicamente
    # com o serviço (D-105): nunca há Sale "solta" antes da conclusão.
    sale = None
    product_total = Decimal("0")
    if body.produtos:
        sale = await build_sale(
            db,
            organization_id=current_user.organization_id,
            unit_id=appt.unit_id,
            client_id=appt.client_id,
            appointment_id=appt.id,
            items=[SaleItemIn(variant_id=i.variant_id, qty=i.qty) for i in body.produtos],
            created_by_user_id=current_user.id,
        )
        product_total = sale.total_amount

    try:
        alloc = allocate_payments(
            [
                PaymentLineIn(p.amount, p.method, p.card_type, p.card_brand)
                for p in body.payments
            ],
            service_total=service_total,
            product_total=product_total,
            tip_total=tip_total,
        )
    except ValueError as exc:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # ── Payment(s) do serviço (split — 1 linha por método) ───────────────────
    service_payments: list[Payment] = []
    for line in alloc.service_lines:
        payment = Payment(
            organization_id=current_user.organization_id,
            appointment_id=appt.id,
            amount=line.amount,
            method=line.method,
            card_type=line.card_type,
            card_brand=line.card_brand,
        )
        db.add(payment)
        service_payments.append(payment)

    if alloc.tip_amount > 0:
        if service_payments:
            service_payments[-1].tip_amount = alloc.tip_amount
        else:
            # Gorjeta sem nenhum pagamento de serviço em dinheiro/cartão/pix
            # associado (ex.: serviço 100% pago por assinatura) — linha
            # própria, mesmo padrão de antes (Payment amount=0 + tip_amount).
            db.add(
                Payment(
                    organization_id=current_user.organization_id,
                    appointment_id=appt.id,
                    amount=Decimal("0"),
                    tip_amount=alloc.tip_amount,
                    method=alloc.tip_method or PaymentMethod.dinheiro,
                    card_type=alloc.tip_card_type,
                    card_brand=alloc.tip_card_brand,
                )
            )

    # ── SalePayment(s) dos produtos (split) ───────────────────────────────────
    if sale is not None:
        for line in alloc.product_lines:
            db.add(
                SalePayment(
                    organization_id=current_user.organization_id,
                    sale_id=sale.id,
                    amount=line.amount,
                    method=line.method,
                    card_type=line.card_type,
                    card_brand=line.card_brand,
                )
            )

    # ── Carteira de crédito do cliente (D-105) ────────────────────────────────
    wallet_used = sum(
        (l.amount for l in (*alloc.service_lines, *alloc.product_lines) if l.method == PaymentMethod.credito_cliente),
        Decimal("0"),
    )
    if alloc.tip_amount > 0 and alloc.tip_method == PaymentMethod.credito_cliente:
        wallet_used += alloc.tip_amount
    if wallet_used > 0:
        await client_wallet.debit(
            db,
            organization_id=current_user.organization_id,
            client_id=appt.client_id,
            amount=wallet_used,
            reference_type="appointment",
            reference_id=appt.id,
            created_by_user_id=current_user.id,
        )

    if not paid_by_membership:
        # Receita de serviço (sem gorjeta/produto) — alinha total_amount com
        # AppointmentItem.price_charged (base de receita/comissão do financeiro)
        # e com a fidelidade.
        appt.total_amount = service_total
        primary_item = min(appt.items, key=lambda i: i.position, default=None)
        if primary_item is not None:
            primary_item.price_charged = service_total
    appt.status = AppointmentStatus.concluido

    # autoflush=False: sem flush as agregações do recalculate não veem este atendimento
    await db.flush()

    # Caixa vivo (D-101): soma só as linhas em DINHEIRO do split geral
    # (serviço + produtos + gorjeta) e lança 1 movimento único. Cartão/Pix/
    # carteira nunca tocam no caixa.
    await cash.resolve_and_post_cash(
        db,
        [(p.amount, p.method) for p in body.payments],
        organization_id=current_user.organization_id,
        unit_id=appt.unit_id,
        reference_type="appointment",
        reference_id=appt.id,
        movement_type=CashMovementType.venda_servico,
        note="Checkout único (serviço + produtos)" if sale is not None else None,
        user_id=current_user.id,
    )

    await _recalculate_loyalty(appt.client_id, current_user.organization_id, db)
    await db.commit()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="appointments.complete",
        resource_type="appointment",
        resource_id=appt_id,
        after={
            "paid_by": "membership" if paid_by_membership else "split",
            "service_amount": float(service_total),
            "product_amount": float(product_total),
            "tip_amount": float(alloc.tip_amount),
            "payments": len(body.payments),
        },
    )

    final_total = float(service_total if not paid_by_membership else appt.total_amount) + float(alloc.tip_amount)
    background_tasks.add_task(push_appointment, appt_id, current_user.organization_id, "upsert")
    return AtendimentoOut(id=appt_id, status="concluido", total_amount=float(final_total))


@router.patch("/atendimento/{appt_id}/faltou", response_model=AtendimentoOut)
async def faltou_atendimento(
    appt_id: Annotated[int, Path(gt=0)],
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AtendimentoOut:
    role, my_barber_id = await resolve_current_role_with_barber(db, current_user)

    appt = await _load_appointment(db, appt_id)
    check_appointment_ownership(appt, role, my_barber_id)
    _require_agendado(appt)

    orig_total = float(appt.total_amount)
    appt.status = AppointmentStatus.faltou
    # Se o atendimento consumia um pacote de mensalidade, devolve o saldo.
    await revert_usage(db, appt_id, reverted_by_user_id=current_user.id)
    await db.commit()

    background_tasks.add_task(push_appointment, appt_id, current_user.organization_id, "delete")
    return AtendimentoOut(id=appt_id, status="faltou", total_amount=orig_total)


@router.patch("/atendimento/{appt_id}/cancelar", response_model=AtendimentoOut)
async def cancelar_atendimento(
    appt_id: Annotated[int, Path(gt=0)],
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AtendimentoOut:
    role, my_barber_id = await resolve_current_role_with_barber(db, current_user)

    appt = await _load_appointment(db, appt_id)
    check_appointment_ownership(appt, role, my_barber_id)
    _require_agendado(appt)

    orig_total = float(appt.total_amount)
    appt.status = AppointmentStatus.cancelado
    # Se o atendimento consumia um pacote de mensalidade, devolve o saldo.
    await revert_usage(db, appt_id, reverted_by_user_id=current_user.id)
    await db.commit()

    background_tasks.add_task(push_appointment, appt_id, current_user.organization_id, "delete")
    return AtendimentoOut(id=appt_id, status="cancelado", total_amount=orig_total)


@router.patch("/atendimento/{appt_id}/estornar-uso", response_model=AtendimentoOut)
async def estornar_uso_atendimento(
    appt_id: Annotated[int, Path(gt=0)],
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AtendimentoOut:
    """Estorna o uso de um atendimento JÁ CONCLUÍDO pago por assinatura.

    Corrige o erro mais comum e antes irreversível: 'Usar agora' por engano, ou
    conclusão debitando a assinatura errada. Cancela o atendimento, devolve 1 uso
    ao saldo (``revert_usage``) e recalcula a fidelidade — tudo na transação do
    request. Só funciona em atendimento ``concluido`` que tenha uso de assinatura
    ativo (não toca atendimentos pagos em dinheiro/cartão/pix).
    """
    role, my_barber_id = await resolve_current_role_with_barber(db, current_user)

    appt = await _load_appointment(db, appt_id)
    check_appointment_ownership(appt, role, my_barber_id)

    if appt.status != AppointmentStatus.concluido:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Só é possível estornar o uso de um atendimento concluído.",
        )
    usage = await usage_for_appointment(db, appt_id)
    if usage is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Este atendimento não foi pago por assinatura (nada a estornar).",
        )

    appt.status = AppointmentStatus.cancelado
    await revert_usage(db, appt_id, reverted_by_user_id=current_user.id)
    await db.flush()
    # A conclusão havia (1) recalculado os agregados legados e (2) CREDITADO
    # pontos (earn) no ledger append-only. O recalc sozinho NÃO desfaz o earn
    # (só credita), então reverte explicitamente os pontos deste agendamento
    # antes de recompor o snapshot — senão o cliente mantém pontos/tier de um
    # atendimento estornado.
    await _reverse_loyalty_points(
        current_user.organization_id, appt.client_id, appt_id, db,
        by_user_id=current_user.id,
    )
    await _recalculate_loyalty(appt.client_id, current_user.organization_id, db)
    await db.commit()
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="appointments.revert_usage",
        resource_type="appointment",
        resource_id=appt_id,
        reason="Estorno de uso de assinatura em atendimento concluído",
    )

    background_tasks.add_task(push_appointment, appt_id, current_user.organization_id, "delete")
    return AtendimentoOut(id=appt_id, status="cancelado", total_amount=float(appt.total_amount))
