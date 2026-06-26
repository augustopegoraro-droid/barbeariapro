"""Módulo do Barbeiro — ações sobre atendimentos do próprio barbeiro."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import check_appointment_ownership
from app.deps import get_current_user, get_tenant_db, resolve_current_role_with_barber
from app.services.calendar_sync import push_appointment
from app.services.loyalty import recalculate as _recalculate_loyalty
from app.services.membership import revert_usage, usage_for_appointment
from models import Appointment, AppointmentItem, Payment, User
from models.enums import AppointmentStatus, PaymentMethod

router = APIRouter(prefix="/barbeiro", tags=["barbeiro"])

_VALID_METHODS = {m.value for m in PaymentMethod}


async def _load_appointment(db: AsyncSession, appt_id: int) -> Appointment:
    row = (
        await db.execute(
            select(Appointment)
            .where(Appointment.id == appt_id)
            .options(selectinload(Appointment.items))
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

class ConcluirRequest(BaseModel):
    # method/amount são opcionais em atendimentos pagos por mensalidade (sem
    # dinheiro); obrigatórios no fluxo normal (validado no endpoint).
    method: Optional[str] = Field(None, description="dinheiro | cartao | pix")
    amount: Optional[float] = Field(None, ge=0, description="Valor cobrado")
    tip_amount: Optional[float] = Field(None, ge=0, description="Gorjeta (opcional)")


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

    usage = await usage_for_appointment(db, appt_id)

    if usage is not None:
        # Atendimento pago por mensalidade: a receita já está rateada nos
        # AppointmentItem.price_charged (reconhecida no uso). NÃO cria Payment
        # (sem dinheiro) e NÃO sobrescreve price_charged. A gorjeta, se houver,
        # ainda é dinheiro e vai para Payment.
        tip = Decimal(str(body.tip_amount)) if body.tip_amount else None
        if tip is not None:
            db.add(Payment(
                organization_id=current_user.organization_id,
                appointment_id=appt.id,
                amount=Decimal("0"),
                tip_amount=tip,
                method=PaymentMethod(body.method) if body.method in _VALID_METHODS else PaymentMethod.dinheiro,
            ))
        appt.status = AppointmentStatus.concluido
        await db.flush()
        await _recalculate_loyalty(appt.client_id, current_user.organization_id, db)
        await db.commit()

        background_tasks.add_task(push_appointment, appt_id, current_user.organization_id, "upsert")
        final_total = float(appt.total_amount) + float(tip or Decimal("0"))
        return AtendimentoOut(id=appt_id, status="concluido", total_amount=final_total)

    # ── fluxo normal (pagamento em dinheiro/cartão/pix) ──────────────────────
    if body.method not in _VALID_METHODS or body.amount is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Informe method ({sorted(_VALID_METHODS)}) e amount.",
        )

    amount = Decimal(str(body.amount))
    tip = Decimal(str(body.tip_amount)) if body.tip_amount else None

    payment = Payment(
        organization_id=current_user.organization_id,
        appointment_id=appt.id,
        amount=amount,
        tip_amount=tip,
        method=PaymentMethod(body.method),
    )
    db.add(payment)

    # Receita de serviço (sem gorjeta) — alinha total_amount com
    # AppointmentItem.price_charged (base de receita/comissão do financeiro) e com
    # a fidelidade. A gorjeta fica só em Payment.tip_amount.
    appt.status = AppointmentStatus.concluido
    appt.total_amount = amount
    primary_item = min(appt.items, key=lambda i: i.position, default=None)
    if primary_item is not None:
        primary_item.price_charged = amount

    # autoflush=False: sem flush as agregações do recalculate não veem este atendimento
    await db.flush()
    await _recalculate_loyalty(appt.client_id, current_user.organization_id, db)
    await db.commit()

    final_total = amount + (tip or Decimal("0"))
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
    await revert_usage(db, appt_id)
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
    await revert_usage(db, appt_id)
    await db.commit()

    background_tasks.add_task(push_appointment, appt_id, current_user.organization_id, "delete")
    return AtendimentoOut(id=appt_id, status="cancelado", total_amount=orig_total)
