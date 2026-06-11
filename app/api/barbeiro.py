"""Módulo do Barbeiro — ações sobre atendimentos do próprio barbeiro."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import check_appointment_ownership, resolve_role_with_barber
from app.deps import get_current_user, get_tenant_db
from models import Appointment, AppointmentItem, Payment, User, UserUnit
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
    method: str = Field(..., description="dinheiro | cartao | pix")
    amount: float = Field(..., ge=0, description="Valor cobrado")
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
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AtendimentoOut:
    if body.method not in _VALID_METHODS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Método inválido. Use: {sorted(_VALID_METHODS)}",
        )

    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    role, my_barber_id = resolve_role_with_barber(list(unit_links))

    appt = await _load_appointment(db, appt_id)
    check_appointment_ownership(appt, role, my_barber_id)
    _require_agendado(appt)

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

    final_total = amount + (tip or Decimal("0"))
    appt.status = AppointmentStatus.concluido
    appt.total_amount = final_total
    await db.commit()

    return AtendimentoOut(id=appt_id, status="concluido", total_amount=float(final_total))


@router.patch("/atendimento/{appt_id}/faltou", response_model=AtendimentoOut)
async def faltou_atendimento(
    appt_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AtendimentoOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    role, my_barber_id = resolve_role_with_barber(list(unit_links))

    appt = await _load_appointment(db, appt_id)
    check_appointment_ownership(appt, role, my_barber_id)
    _require_agendado(appt)

    orig_total = float(appt.total_amount)
    appt.status = AppointmentStatus.faltou
    await db.commit()

    return AtendimentoOut(id=appt_id, status="faltou", total_amount=orig_total)


@router.patch("/atendimento/{appt_id}/cancelar", response_model=AtendimentoOut)
async def cancelar_atendimento(
    appt_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AtendimentoOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    role, my_barber_id = resolve_role_with_barber(list(unit_links))

    appt = await _load_appointment(db, appt_id)
    check_appointment_ownership(appt, role, my_barber_id)
    _require_agendado(appt)

    orig_total = float(appt.total_amount)
    appt.status = AppointmentStatus.cancelado
    await db.commit()

    return AtendimentoOut(id=appt_id, status="cancelado", total_amount=orig_total)
