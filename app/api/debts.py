"""Contas a receber — débitos de clientes (`client_debts`, migration 0023).

Painel do gestor: listar dívidas em aberto, ver total e marcar como pago. Dado
financeiro → `require_manager_access`. Multi-tenant via RLS do token.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.core.rbac import require_manager_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from models import ClientDebt, User

router = APIRouter(prefix="/admin/debts", tags=["debts"])

TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def _guard(db: AsyncSession, user: User) -> None:
    await require_permission(db, user, "finance.payments.view")


class DebtOut(BaseModel):
    id: int
    client_id: Optional[int]
    client_name: str
    amount: Decimal
    debt_date: Optional[date]
    service_desc: Optional[str]
    professional: Optional[str]
    kind: str
    status: str
    created_at: datetime
    paid_at: Optional[datetime]


class DebtSummaryOut(BaseModel):
    open_count: int
    open_total: Decimal
    paid_count: int


@router.get("", response_model=list[DebtOut])
async def list_debts(
    db: TenantDB,
    current_user: CurrentUser,
    status_filter: Annotated[
        Optional[str], Query(alias="status", description="aberto | pago (vazio = todos)")
    ] = "aberto",
) -> list[ClientDebt]:
    await _guard(db, current_user)
    stmt = select(ClientDebt)
    if status_filter:
        stmt = stmt.where(ClientDebt.status == status_filter)
    stmt = stmt.order_by(ClientDebt.debt_date.desc().nullslast(), ClientDebt.id.desc())
    return list((await db.execute(stmt)).scalars().all())


@router.get("/summary", response_model=DebtSummaryOut)
async def debts_summary(db: TenantDB, current_user: CurrentUser) -> DebtSummaryOut:
    await _guard(db, current_user)
    open_count, open_total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(ClientDebt.amount), 0)).where(
                ClientDebt.status == "aberto"
            )
        )
    ).one()
    paid_count = (
        await db.execute(
            select(func.count()).where(ClientDebt.status == "pago")
        )
    ).scalar_one()
    return DebtSummaryOut(
        open_count=open_count, open_total=open_total, paid_count=paid_count
    )


async def _get_debt(db: AsyncSession, debt_id: int) -> ClientDebt:
    debt = (
        await db.execute(select(ClientDebt).where(ClientDebt.id == debt_id))
    ).scalar_one_or_none()
    if debt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Débito não encontrado.")
    return debt


@router.post("/{debt_id}/pay", response_model=DebtOut)
async def mark_paid(debt_id: int, db: TenantDB, current_user: CurrentUser) -> ClientDebt:
    await _guard(db, current_user)
    debt = await _get_debt(db, debt_id)
    debt.status = "pago"
    debt.paid_at = datetime.now(timezone.utc)
    await db.flush()
    return debt


@router.post("/{debt_id}/reopen", response_model=DebtOut)
async def reopen(debt_id: int, db: TenantDB, current_user: CurrentUser) -> ClientDebt:
    await _guard(db, current_user)
    debt = await _get_debt(db, debt_id)
    debt.status = "aberto"
    debt.paid_at = None
    await db.flush()
    return debt
