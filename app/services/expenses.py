"""Despesas ricas + contas a pagar + despesas recorrentes (D-102).

Porta única da lógica de despesa: criação (com forma de pagamento, subgrupo,
beneficiário e status pago/a_pagar), transição `a_pagar ↔ pago` e
materialização mensal das recorrências. A integração com o Caixa vivo (D-101)
vale só quando `method == dinheiro` e `status == pago` — qualquer outra forma
fica só no Financeiro/DRE.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_local
from app.services import cash_register as cash
from models import (
    CashMovement,
    CashMovementType,
    Expense,
    ExpenseCategory,
    ExpenseMethod,
    ExpenseRecurrence,
    ExpenseStatus,
)

SUBGROUPS = {"fixa", "variavel", "pessoal", "impostos", "outros"}


def validate_subgroup(subgroup: Optional[str]) -> Optional[str]:
    """Normaliza/valida o slug de subgrupo. `''`/`None` → `None`; inválido → 422."""
    if subgroup is None:
        return None
    subgroup = subgroup.strip()
    if not subgroup:
        return None
    if subgroup not in SUBGROUPS:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Subgrupo inválido."
        )
    return subgroup


async def resolve_category(
    db: AsyncSession, *, organization_id: int, name: str
) -> ExpenseCategory:
    """Reusa a categoria por nome (case-insensitive, RLS-scoped) ou cria."""
    name = name.strip()
    category = (
        await db.execute(
            select(ExpenseCategory).where(
                func.lower(ExpenseCategory.name) == name.lower()
            )
        )
    ).scalar_one_or_none()
    if category is None:
        category = ExpenseCategory(organization_id=organization_id, name=name)
        db.add(category)
        await db.flush()
    return category


async def _category_name(db: AsyncSession, category_id: int) -> str:
    return (
        await db.execute(
            select(ExpenseCategory.name).where(ExpenseCategory.id == category_id)
        )
    ).scalar_one()


async def create_expense(
    db: AsyncSession,
    *,
    organization_id: int,
    category_name: str,
    amount: Decimal,
    competence_month: date,
    user_id: int,
    method: Optional[ExpenseMethod] = None,
    subgroup: Optional[str] = None,
    payee: Optional[str] = None,
    status: ExpenseStatus = ExpenseStatus.pago,
    due_date: Optional[date] = None,
    note: Optional[str] = None,
    recurrence_id: Optional[int] = None,
) -> tuple[Expense, str]:
    """Cria a despesa e — só se `pago` + `dinheiro` — lança a saída no caixa
    aberto (checando o enforcement ANTES de gravar). Retorna `(expense, nome
    da categoria)`."""
    subgroup = validate_subgroup(subgroup)
    category = await resolve_category(
        db, organization_id=organization_id, name=category_name
    )
    unit_id = await cash.resolve_unit_id(db)

    pays_cash_now = (
        status == ExpenseStatus.pago and method == ExpenseMethod.dinheiro
    )
    cash_session = None
    if pays_cash_now:
        cash_session = await cash.require_open_session(
            db, organization_id=organization_id, unit_id=unit_id
        )

    expense = Expense(
        organization_id=organization_id,
        unit_id=unit_id,
        category_id=category.id,
        amount=amount,
        competence_month=competence_month,
        method=method,
        subgroup=subgroup,
        payee=(payee.strip() if payee and payee.strip() else None),
        status=status,
        due_date=due_date if status == ExpenseStatus.a_pagar else None,
        paid_at=(today_local() if status == ExpenseStatus.pago else None),
        note=(note or None),
        recurrence_id=recurrence_id,
    )
    db.add(expense)
    await db.flush()

    if cash_session is not None:
        await cash.post_movement(
            db,
            cash_session,
            type=CashMovementType.despesa,
            amount=amount,
            reference_type="expense",
            reference_id=expense.id,
            note=(note or f"Despesa: {category.name}"),
            user_id=user_id,
        )
    return expense, category.name


async def mark_paid(
    db: AsyncSession,
    expense: Expense,
    *,
    organization_id: int,
    user_id: int,
    method: Optional[ExpenseMethod] = None,
    paid_at: Optional[date] = None,
) -> Expense:
    """Transição `a_pagar → pago`. Se `method == dinheiro` e há caixa aberto,
    lança a saída `despesa`; com enforcement ligado e sem caixa → 409
    `cash_register_closed`."""
    if expense.status == ExpenseStatus.pago:
        return expense

    effective_method = method if method is not None else expense.method
    # Checa o caixa ANTES de mutar (mesmo padrão de `create_expense`).
    cash_session = None
    if effective_method == ExpenseMethod.dinheiro:
        cash_session = await cash.require_open_session(
            db, organization_id=organization_id, unit_id=expense.unit_id
        )

    if method is not None:
        expense.method = method
    expense.status = ExpenseStatus.pago
    expense.paid_at = paid_at or today_local()
    await db.flush()

    if cash_session is not None:
        cat_name = await _category_name(db, expense.category_id)
        await cash.post_movement(
            db,
            cash_session,
            type=CashMovementType.despesa,
            amount=expense.amount,
            reference_type="expense",
            reference_id=expense.id,
            note=f"Despesa paga: {cat_name}",
            user_id=user_id,
        )
    return expense


async def unmark_paid(
    db: AsyncSession, expense: Expense, *, user_id: int
) -> Expense:
    """Transição `pago → a_pagar`. Se a despesa saiu do caixa (movimento
    `expense`), lança um `ajuste` compensatório NO CAIXA ABERTO ATUAL — mesmo
    padrão do `remover_despesa` (D-101). Sem caixa aberto, só muda o status."""
    if expense.status == ExpenseStatus.a_pagar:
        return expense

    cash_mov = (
        await db.execute(
            select(CashMovement)
            .where(CashMovement.reference_type == "expense")
            .where(CashMovement.reference_id == expense.id)
        )
    ).scalar_one_or_none()
    if cash_mov is not None:
        open_session = await cash.get_open_session(db, expense.unit_id)
        if open_session is not None:
            await cash.post_movement(
                db,
                open_session,
                type=CashMovementType.ajuste,
                amount=cash_mov.amount,
                reference_type="expense_unpay",
                reference_id=expense.id,
                note="Despesa voltou para a pagar",
                user_id=user_id,
            )

    expense.status = ExpenseStatus.a_pagar
    expense.paid_at = None
    if expense.due_date is None:
        expense.due_date = today_local()
    await db.flush()
    return expense


async def materialize_recurrences(
    db: AsyncSession, *, organization_id: int, today: date
) -> dict:
    """Para cada recorrência ativa, cria a conta `a_pagar` do mês corrente
    (`competence_month` = 1º dia do mês; `due_date` = dia `day_of_month`).
    Idempotente pelo índice único parcial `expenses_recurrence_month_unique`."""
    competence = today.replace(day=1)
    recs = (
        await db.execute(
            select(ExpenseRecurrence).where(ExpenseRecurrence.active.is_(True))
        )
    ).scalars().all()

    created = skipped = 0
    for rec in recs:
        exists = (
            await db.execute(
                select(Expense.id)
                .where(Expense.recurrence_id == rec.id)
                .where(Expense.competence_month == competence)
            )
        ).scalar_one_or_none()
        if exists is not None:
            skipped += 1
            continue

        due = competence.replace(day=rec.day_of_month)  # day_of_month ∈ [1, 28]
        expense = Expense(
            organization_id=rec.organization_id,
            unit_id=rec.unit_id,
            category_id=rec.category_id,
            amount=rec.amount,
            competence_month=competence,
            method=rec.method,
            subgroup=rec.subgroup,
            payee=rec.payee,
            status=ExpenseStatus.a_pagar,
            due_date=due,
            paid_at=None,
            note=rec.note,
            recurrence_id=rec.id,
        )
        db.add(expense)
        try:
            async with db.begin_nested():
                await db.flush()
            created += 1
        except IntegrityError:
            # Corrida com outra execução do cron — o índice único parcial pega.
            skipped += 1
    return {"created": created, "skipped": skipped}
