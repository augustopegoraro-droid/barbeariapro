"""Caixa vivo (D-101) — abrir/fechar turno em tempo real + ledger de movimentos.

Controla o DINHEIRO físico da gaveta: troco inicial, entradas em dinheiro
(automáticas — conclusão de atendimento / venda / despesa em dinheiro, via
`app/services/cash_register.py`), sangria/suprimento/ajuste manuais, e
contagem de fechamento com divergência. Cartão/Pix entram só como total
informativo do turno.

Não confundir com `GET /financeiro/caixa` (histórico de fechamento diário
migrado da Trinks, D-59) — read-only e de outra tabela.

Permissões: `cash.session.view` (ler) / `cash.session.operate` (abrir/fechar/
lançar). Ambas no bloco `_OPERATIONS` → owner/manager/recepção. Barbeiro fora.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.services.audit import record_event
from app.services import cash_register as cash
from models import CashMovement, CashMovementType, CashSession, CashSessionStatus, User

router = APIRouter(prefix="/caixa", tags=["caixa"])

_MANUAL_TYPES = {t.value for t in cash.MANUAL_TYPES}


async def _require_view(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "cash.session.view")


async def _require_operate(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "cash.session.operate")


# ── Schemas ──────────────────────────────────────────────────────────────────


class AbrirCaixaIn(BaseModel):
    opening_float: Decimal = Field(..., ge=Decimal("0"), description="Troco inicial na gaveta")


class FecharCaixaIn(BaseModel):
    counted_amount: Decimal = Field(..., ge=Decimal("0"), description="Dinheiro contado na gaveta")
    note: Optional[str] = Field(None, max_length=500)


class MovimentoIn(BaseModel):
    type: CashMovementType
    amount: Decimal = Field(..., description="Valor; negativo só é aceito em 'ajuste'.")
    note: Optional[str] = Field(None, max_length=500)


class MovimentoOut(BaseModel):
    id: int
    session_id: int
    type: CashMovementType
    amount: float
    reference_type: Optional[str]
    reference_id: Optional[int]
    note: Optional[str]
    created_by_user_id: Optional[int]
    created_at: datetime


class SaldoOut(BaseModel):
    opening_float: float
    expected_cash: float
    cash_in: float
    cash_out: float
    adjustments: float
    card_total: float
    pix_total: float
    movement_count: int
    by_type: dict[str, float]


class CaixaSessaoOut(BaseModel):
    id: int
    status: CashSessionStatus
    opened_at: datetime
    opened_by_user_id: Optional[int]
    opening_float: float
    closed_at: Optional[datetime]
    closed_by_user_id: Optional[int]
    counted_amount: Optional[float]
    expected_amount: Optional[float]
    difference: Optional[float]
    closing_note: Optional[str]


class CaixaAtualOut(BaseModel):
    session: Optional[CaixaSessaoOut]
    balance: Optional[SaldoOut]


class CaixaDetalheOut(BaseModel):
    session: CaixaSessaoOut
    balance: SaldoOut
    movements: list[MovimentoOut]


def _session_out(s: CashSession) -> CaixaSessaoOut:
    return CaixaSessaoOut(
        id=s.id,
        status=s.status,
        opened_at=s.opened_at,
        opened_by_user_id=s.opened_by_user_id,
        opening_float=float(s.opening_float),
        closed_at=s.closed_at,
        closed_by_user_id=s.closed_by_user_id,
        counted_amount=float(s.counted_amount) if s.counted_amount is not None else None,
        expected_amount=float(s.expected_amount) if s.expected_amount is not None else None,
        difference=float(s.difference) if s.difference is not None else None,
        closing_note=s.closing_note,
    )


def _balance_out(b: dict) -> SaldoOut:
    return SaldoOut(
        opening_float=float(b["opening_float"]),
        expected_cash=float(b["expected_cash"]),
        cash_in=float(b["cash_in"]),
        cash_out=float(b["cash_out"]),
        adjustments=float(b["adjustments"]),
        card_total=float(b["card_total"]),
        pix_total=float(b["pix_total"]),
        movement_count=b["movement_count"],
        by_type={k: float(v) for k, v in b["by_type"].items()},
    )


def _movement_out(m: CashMovement) -> MovimentoOut:
    return MovimentoOut(
        id=m.id,
        session_id=m.session_id,
        type=m.type,
        amount=float(m.amount),
        reference_type=m.reference_type,
        reference_id=m.reference_id,
        note=m.note,
        created_by_user_id=m.created_by_user_id,
        created_at=m.created_at,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/atual", response_model=CaixaAtualOut)
async def caixa_atual(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CaixaAtualOut:
    await _require_view(db, current_user)
    unit_id = await cash.resolve_unit_id(db)
    session = await cash.get_open_session(db, unit_id)
    if session is None:
        return CaixaAtualOut(session=None, balance=None)
    balance = await cash.session_balance(db, session)
    return CaixaAtualOut(session=_session_out(session), balance=_balance_out(balance))


@router.post("/abrir", response_model=CaixaDetalheOut, status_code=http_status.HTTP_201_CREATED)
async def abrir_caixa(
    body: AbrirCaixaIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CaixaDetalheOut:
    await _require_operate(db, current_user)
    unit_id = await cash.resolve_unit_id(db)
    session = await cash.open_session(
        db,
        organization_id=current_user.organization_id,
        unit_id=unit_id,
        opening_float=body.opening_float,
        user_id=current_user.id,
    )
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="cash.session.open",
        resource_type="cash_session",
        resource_id=session.id,
        after={"opening_float": float(session.opening_float)},
    )
    balance = await cash.session_balance(db, session)
    return CaixaDetalheOut(
        session=_session_out(session), balance=_balance_out(balance), movements=[]
    )


@router.post("/fechar", response_model=CaixaDetalheOut)
async def fechar_caixa(
    body: FecharCaixaIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CaixaDetalheOut:
    await _require_operate(db, current_user)
    unit_id = await cash.resolve_unit_id(db)
    session = await cash.get_open_session(db, unit_id)
    if session is None:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Nenhum caixa aberto para fechar.")
    session = await cash.close_session(
        db,
        session,
        counted_amount=body.counted_amount,
        note=body.note,
        user_id=current_user.id,
    )
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="cash.session.close",
        resource_type="cash_session",
        resource_id=session.id,
        after={
            "counted_amount": float(session.counted_amount),
            "expected_amount": float(session.expected_amount),
            "difference": float(session.difference),
        },
    )
    full = await cash.load_session(db, session.id)
    balance = await cash.session_balance(db, full)
    return CaixaDetalheOut(
        session=_session_out(full),
        balance=_balance_out(balance),
        movements=[_movement_out(m) for m in full.movements],
    )


@router.post("/movimentos", response_model=MovimentoOut, status_code=http_status.HTTP_201_CREATED)
async def lancar_movimento(
    body: MovimentoIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MovimentoOut:
    await _require_operate(db, current_user)
    if body.type.value not in _MANUAL_TYPES:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Só suprimento, sangria, despesa ou ajuste podem ser lançados à mão.",
        )
    unit_id = await cash.resolve_unit_id(db)
    session = await cash.get_open_session(db, unit_id)
    if session is None:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT, "Abra o caixa antes de lançar um movimento."
        )
    movement = await cash.post_movement(
        db,
        session,
        type=body.type,
        amount=body.amount,
        reference_type="manual",
        note=body.note,
        user_id=current_user.id,
    )
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="cash.movement.create",
        resource_type="cash_movement",
        resource_id=movement.id,
        after={"type": movement.type.value, "amount": float(movement.amount), "note": movement.note},
    )
    return _movement_out(movement)


@router.get("/movimentos", response_model=list[MovimentoOut])
async def listar_movimentos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    session_id: int = Query(..., gt=0),
) -> list[MovimentoOut]:
    await _require_view(db, current_user)
    rows = (
        await db.execute(
            select(CashMovement)
            .where(CashMovement.session_id == session_id)
            .order_by(CashMovement.created_at, CashMovement.id)
        )
    ).scalars().all()
    return [_movement_out(m) for m in rows]


@router.get("", response_model=list[CaixaSessaoOut])
async def listar_sessoes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    status_filter: Optional[CashSessionStatus] = Query(None, alias="status"),
    limit: int = Query(60, ge=1, le=200),
) -> list[CaixaSessaoOut]:
    await _require_view(db, current_user)
    stmt = select(CashSession).order_by(CashSession.opened_at.desc(), CashSession.id.desc()).limit(limit)
    if date_from is not None:
        stmt = stmt.where(CashSession.opened_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(CashSession.opened_at < date_to)
    if status_filter is not None:
        stmt = stmt.where(CashSession.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    return [_session_out(s) for s in rows]


@router.get("/{session_id}", response_model=CaixaDetalheOut)
async def obter_sessao(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    session_id: int = Path(..., gt=0),
) -> CaixaDetalheOut:
    await _require_view(db, current_user)
    session = await cash.load_session(db, session_id)
    balance = await cash.session_balance(db, session)
    return CaixaDetalheOut(
        session=_session_out(session),
        balance=_balance_out(balance),
        movements=[_movement_out(m) for m in session.movements],
    )
