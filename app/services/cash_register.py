"""Caixa vivo (D-101) — porta ÚNICA de escrita no caixa.

Turno (`CashSession`) + ledger append-only (`CashMovement`). Nenhum outro
módulo deve inserir em `cash_movements` ou mudar `CashSession.status`
diretamente — sempre por aqui.

Integrações (auto-post + bloqueio) chamam `require_open_session(...)` ANTES de
mutar estado e `post_movement(...)` depois, e só quando o método é `dinheiro`
(cartão/Pix nunca tocam no caixa). `post_movement` é idempotente por
`(reference_type, reference_id)` para `payment`/`sale`/`expense`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import (
    CashMovement,
    CashMovementType,
    CashSession,
    CashSessionStatus,
    Organization,
    Payment,
    PaymentMethod,
    SalePayment,
    Unit,
)

# Tipos que somam ao dinheiro esperado na gaveta (entradas).
_INFLOW = {
    CashMovementType.venda_servico,
    CashMovementType.venda_produto,
    CashMovementType.suprimento,
}
# Tipos que subtraem (saídas). `ajuste` é tratado à parte — `amount` já é assinado.
_OUTFLOW = {CashMovementType.sangria, CashMovementType.despesa}

# Movimentos que a recepção lança à mão (os demais são automáticos).
MANUAL_TYPES = {
    CashMovementType.suprimento,
    CashMovementType.sangria,
    CashMovementType.despesa,
    CashMovementType.ajuste,
}
# Manuais que exigem justificativa.
_NOTE_REQUIRED = {
    CashMovementType.sangria,
    CashMovementType.despesa,
    CashMovementType.ajuste,
}


async def resolve_unit_id(db: AsyncSession) -> int:
    """Unidade principal da org (mais antiga ativa). RLS já escopa por tenant."""
    unit_id = (
        await db.execute(
            select(Unit.id).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1)
        )
    ).scalar_one_or_none()
    if unit_id is None:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT, "Organização sem unidade cadastrada."
        )
    return unit_id


async def get_open_session(db: AsyncSession, unit_id: int) -> Optional[CashSession]:
    return (
        await db.execute(
            select(CashSession)
            .where(CashSession.unit_id == unit_id)
            .where(CashSession.status == CashSessionStatus.aberto)
        )
    ).scalar_one_or_none()


async def load_session(db: AsyncSession, session_id: int) -> CashSession:
    session = (
        await db.execute(
            select(CashSession)
            .options(selectinload(CashSession.movements))
            .where(CashSession.id == session_id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Caixa não encontrado.")
    return session


async def open_session(
    db: AsyncSession,
    *,
    organization_id: int,
    unit_id: int,
    opening_float: Decimal,
    user_id: int,
) -> CashSession:
    if opening_float < 0:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "O troco inicial não pode ser negativo.",
        )
    session = CashSession(
        organization_id=organization_id,
        unit_id=unit_id,
        status=CashSessionStatus.aberto,
        opening_float=opening_float,
        opened_by_user_id=user_id,
    )
    db.add(session)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        # Índice único parcial `cash_sessions_one_open_per_unit` — corrida com
        # outra abertura. Savepoint desfeito; a transação do request segue viva.
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Já existe um caixa aberto — feche-o antes de abrir outro.",
        ) from exc
    return session


async def post_movement(
    db: AsyncSession,
    session: CashSession,
    *,
    type: CashMovementType,
    amount: Decimal,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    note: Optional[str] = None,
    user_id: Optional[int] = None,
) -> CashMovement:
    """Insere um movimento no ledger. Idempotente por `(reference_type,
    reference_id)` para `payment`/`sale`/`expense`: se já existe, devolve o
    movimento existente sem duplicar."""
    if session.status != CashSessionStatus.aberto:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT, "O caixa já está fechado."
        )
    if type != CashMovementType.ajuste and amount < 0:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Só um ajuste pode ter valor negativo.",
        )
    if type in _NOTE_REQUIRED and not (note or "").strip():
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Informe o motivo do lançamento.",
        )

    # Idempotência por referência (retry / duplo disparo): se já existe um
    # movimento para este `Payment`/`Sale`/`Expense`, devolve o existente. O
    # índice único parcial `cash_movements_ref_unique` é o backstop de corrida —
    # na prática a conclusão de atendimento já é serializada pelo FOR UPDATE do
    # agendamento, e venda/despesa são inserts únicos.
    if reference_type in ("payment", "sale", "expense") and reference_id is not None:
        existing = (
            await db.execute(
                select(CashMovement)
                .where(CashMovement.reference_type == reference_type)
                .where(CashMovement.reference_id == reference_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    movement = CashMovement(
        organization_id=session.organization_id,
        session_id=session.id,
        type=type,
        amount=amount,
        reference_type=reference_type,
        reference_id=reference_id,
        note=(note or None),
        created_by_user_id=user_id,
    )
    db.add(movement)
    await db.flush()
    return movement


async def session_balance(db: AsyncSession, session: CashSession) -> dict:
    """Saldo ao vivo do turno. `expected_cash` é o que deveria haver de
    DINHEIRO na gaveta; `card_total`/`pix_total` são informativos (não entram
    no esperado nem geram movimento)."""
    rows = (
        await db.execute(
            select(CashMovement.type, func.coalesce(func.sum(CashMovement.amount), 0))
            .where(CashMovement.session_id == session.id)
            .group_by(CashMovement.type)
        )
    ).all()
    by_type: dict[str, Decimal] = {t.value: Decimal("0") for t in CashMovementType}
    total_count = 0
    for mtype, total in rows:
        by_type[mtype.value] = Decimal(total)

    count = (
        await db.execute(
            select(func.count())
            .select_from(CashMovement)
            .where(CashMovement.session_id == session.id)
        )
    ).scalar_one()
    total_count = int(count)

    inflow = sum((by_type[t.value] for t in _INFLOW), Decimal("0"))
    outflow = sum((by_type[t.value] for t in _OUTFLOW), Decimal("0"))
    adjust = by_type[CashMovementType.ajuste.value]
    expected_cash = session.opening_float + inflow - outflow + adjust

    window_end = session.closed_at or datetime.now(timezone.utc)
    card_total, pix_total = await _other_methods(db, session.opened_at, window_end)

    return {
        "opening_float": session.opening_float,
        "by_type": {k: v for k, v in by_type.items()},
        "cash_in": inflow,
        "cash_out": outflow,
        "adjustments": adjust,
        "expected_cash": expected_cash,
        "movement_count": total_count,
        "card_total": card_total,
        "pix_total": pix_total,
    }


async def _other_methods(
    db: AsyncSession, start: datetime, end: datetime
) -> tuple[Decimal, Decimal]:
    """Totais de cartão/Pix na janela do turno — só exibição."""
    totals = {PaymentMethod.cartao: Decimal("0"), PaymentMethod.pix: Decimal("0")}
    for model in (Payment, SalePayment):
        rows = (
            await db.execute(
                select(model.method, func.coalesce(func.sum(model.amount), 0))
                .where(model.method.in_([PaymentMethod.cartao, PaymentMethod.pix]))
                .where(model.paid_at >= start)
                .where(model.paid_at <= end)
                .group_by(model.method)
            )
        ).all()
        for method, total in rows:
            totals[method] += Decimal(total)
    return totals[PaymentMethod.cartao], totals[PaymentMethod.pix]


async def close_session(
    db: AsyncSession,
    session: CashSession,
    *,
    counted_amount: Decimal,
    note: Optional[str],
    user_id: int,
) -> CashSession:
    if session.status != CashSessionStatus.aberto:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT, "Este caixa já foi fechado."
        )
    if counted_amount < 0:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "O dinheiro contado não pode ser negativo.",
        )
    balance = await session_balance(db, session)
    expected = Decimal(balance["expected_cash"])
    session.status = CashSessionStatus.fechado
    session.closed_at = datetime.now(timezone.utc)
    session.closed_by_user_id = user_id
    session.counted_amount = counted_amount
    session.expected_amount = expected
    session.difference = counted_amount - expected
    session.closing_note = (note or None)
    await db.flush()
    return session


async def require_open_session(
    db: AsyncSession, *, organization_id: int, unit_id: int
) -> Optional[CashSession]:
    """Barreira para recebimentos em DINHEIRO. Se o enforcement da org estiver
    ligado e não houver caixa aberto → 409 com `code=cash_register_closed`
    (para o frontend). Se estiver desligado, devolve `None` e o fluxo segue
    sem vínculo de caixa."""
    session = await get_open_session(db, unit_id)
    if session is not None:
        return session

    enforced = (
        await db.execute(
            select(Organization.cash_register_enforced).where(
                Organization.id == organization_id
            )
        )
    ).scalar_one_or_none()
    if not enforced:
        return None

    raise HTTPException(
        status_code=http_status.HTTP_409_CONFLICT,
        detail={
            "detail": "Abra o caixa para receber em dinheiro.",
            "code": "cash_register_closed",
        },
    )
