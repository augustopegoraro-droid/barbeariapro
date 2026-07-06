"""Endpoints financeiros: resumo do dia, visão mensal, despesas e export CSV."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import local_date
from app.core.rbac import require_manager_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.services.management import barber_revenue_rows
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    CashDailyClosing,
    Client,
    DreMonthlyLine,
    Expense,
    ExpenseCategory,
    Payment,
    Service,
    Unit,
    User,
)
from models.enums import PaymentMethod

router = APIRouter(prefix="/financeiro", tags=["financeiro"])


class MethodOut(BaseModel):
    method: str
    amount: float
    count: int


class BarberOut(BaseModel):
    barber_id: int
    barber_name: str
    appointment_count: int
    revenue: float
    commission: float


class ApptFinanceOut(BaseModel):
    id: int
    client_name: str
    barber_name: str
    service_name: str
    total_amount: float
    start_at: str


class FinanceiroOut(BaseModel):
    date: str
    total_revenue: float
    concluido_count: int
    agendado_count: int
    by_method: list[MethodOut]
    by_barber: list[BarberOut]
    appointments: list[ApptFinanceOut]


@router.get("", response_model=FinanceiroOut)
async def get_financeiro(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    date: date = Query(..., description="Data no formato YYYY-MM-DD"),
) -> FinanceiroOut:
    require_manager_access(await resolve_current_role(db, current_user))

    # --- Receita por barbeiro (via appointment_items.price_charged) ----------
    barber_rows = (
        await db.execute(
            select(
                Barber.id,
                Barber.name,
                Barber.commission_pct,
                func.count(Appointment.id.distinct()).label("appt_count"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("revenue"),
            )
            .select_from(AppointmentItem)
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(local_date(Appointment.start_at) == date)
            .group_by(Barber.id, Barber.name, Barber.commission_pct)
            .order_by(func.sum(AppointmentItem.price_charged).desc())
        )
    ).all()

    by_barber = [
        BarberOut(
            barber_id=r.id,
            barber_name=r.name,
            appointment_count=r.appt_count,
            revenue=float(r.revenue),
            commission=float(Decimal(str(r.revenue)) * r.commission_pct),
        )
        for r in barber_rows
    ]

    total_revenue = sum(b.revenue for b in by_barber)

    # --- Contagem de agendamentos do dia -------------------------------------
    counts = (
        await db.execute(
            select(
                Appointment.status,
                func.count(Appointment.id).label("cnt"),
            )
            .where(local_date(Appointment.start_at) == date)
            .group_by(Appointment.status)
        )
    ).all()

    concluido_count = next((r.cnt for r in counts if r.status == AppointmentStatus.concluido), 0)
    agendado_count  = next((r.cnt for r in counts if r.status == AppointmentStatus.agendado), 0)

    # --- Breakdown por método de pagamento (tabela payments) -----------------
    method_rows = (
        await db.execute(
            select(
                Payment.method,
                func.sum(Payment.amount + func.coalesce(Payment.tip_amount, 0)).label("total"),
                func.count(Payment.id).label("cnt"),
            )
            .where(local_date(Payment.paid_at) == date)
            .group_by(Payment.method)
            .order_by(func.sum(Payment.amount).desc())
        )
    ).all()

    by_method = [
        MethodOut(method=r.method.value, amount=float(r.total), count=r.cnt)
        for r in method_rows
    ]

    # --- Lista de agendamentos concluídos com detalhes -----------------------
    appt_rows = (
        await db.execute(
            select(
                Appointment.id,
                Appointment.total_amount,
                Appointment.start_at,
                Client.name.label("client_name"),
                Barber.name.label("barber_name"),
                Service.name.label("service_name"),
            )
            .join(Client, Client.id == Appointment.client_id)
            .outerjoin(
                AppointmentItem,
                (AppointmentItem.appointment_id == Appointment.id)
                & (AppointmentItem.position == 1),
            )
            .outerjoin(Barber, Barber.id == AppointmentItem.barber_id)
            .outerjoin(Service, Service.id == AppointmentItem.service_id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(local_date(Appointment.start_at) == date)
            .order_by(Appointment.start_at)
        )
    ).all()

    appointments = [
        ApptFinanceOut(
            id=r.id,
            client_name=r.client_name,
            barber_name=r.barber_name or "—",
            service_name=r.service_name or "—",
            total_amount=float(r.total_amount),
            start_at=r.start_at.isoformat(),
        )
        for r in appt_rows
    ]

    return FinanceiroOut(
        date=date.isoformat(),
        total_revenue=total_revenue,
        concluido_count=concluido_count,
        agendado_count=agendado_count,
        by_method=by_method,
        by_barber=by_barber,
        appointments=appointments,
    )


# ─── helpers compartilhados ───────────────────────────────────────────────────

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


async def _require_manager(db: AsyncSession, user: User) -> None:
    require_manager_access(await resolve_current_role(db, user))


def _month_range(month: str) -> tuple[date, date]:
    """'YYYY-MM' → (primeiro dia, último dia) do mês."""
    if not _MONTH_RE.match(month):
        raise HTTPException(422, "Mês inválido. Use o formato YYYY-MM.")
    y, m = int(month[:4]), int(month[5:7])
    first = date(y, m, 1)
    next_month = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return first, next_month - timedelta(days=1)


# A query de receita por barbeiro vive em app.services.management
# (barber_revenue_rows), compartilhada com as tools de gestão (D-52).


# ─── GET /financeiro/mensal ───────────────────────────────────────────────────

class ExpenseOut(BaseModel):
    id: int
    category: str
    amount: float
    competence_month: str
    note: Optional[str]


class FinanceiroMensalOut(BaseModel):
    month: str
    total_revenue: float
    total_commission: float
    total_expenses: float
    net: float
    concluido_count: int
    by_method: list[MethodOut]
    by_barber: list[BarberOut]
    expenses: list[ExpenseOut]


@router.get("/mensal", response_model=FinanceiroMensalOut)
async def get_financeiro_mensal(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    month: str = Query(..., description="Mês no formato YYYY-MM"),
) -> FinanceiroMensalOut:
    await _require_manager(db, current_user)
    date_from, date_to = _month_range(month)

    barber_rows = await barber_revenue_rows(db, date_from, date_to)
    by_barber = [
        BarberOut(
            barber_id=r.id,
            barber_name=r.name,
            appointment_count=r.appt_count,
            revenue=float(r.revenue),
            commission=float(Decimal(str(r.revenue)) * r.commission_pct),
        )
        for r in barber_rows
    ]
    total_revenue = sum(b.revenue for b in by_barber)
    total_commission = sum(b.commission for b in by_barber)

    concluido_count = (
        await db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(local_date(Appointment.start_at) >= date_from)
            .where(local_date(Appointment.start_at) <= date_to)
        )
    ).scalar_one()

    method_rows = (
        await db.execute(
            select(
                Payment.method,
                func.sum(Payment.amount + func.coalesce(Payment.tip_amount, 0)).label("total"),
                func.count(Payment.id).label("cnt"),
            )
            .where(local_date(Payment.paid_at) >= date_from)
            .where(local_date(Payment.paid_at) <= date_to)
            .group_by(Payment.method)
            .order_by(func.sum(Payment.amount).desc())
        )
    ).all()
    by_method = [
        MethodOut(method=r.method.value, amount=float(r.total), count=r.cnt)
        for r in method_rows
    ]

    expense_rows = (
        await db.execute(
            select(Expense, ExpenseCategory.name.label("category_name"))
            .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(Expense.competence_month == date_from)
            .order_by(Expense.created_at.desc())
        )
    ).all()
    expenses = [
        ExpenseOut(
            id=e.id,
            category=cat_name,
            amount=float(e.amount),
            competence_month=e.competence_month.isoformat(),
            note=e.note,
        )
        for e, cat_name in expense_rows
    ]
    total_expenses = sum(e.amount for e in expenses)

    return FinanceiroMensalOut(
        month=month,
        total_revenue=total_revenue,
        total_commission=total_commission,
        total_expenses=total_expenses,
        net=total_revenue - total_commission - total_expenses,
        concluido_count=concluido_count,
        by_method=by_method,
        by_barber=by_barber,
        expenses=expenses,
    )


# ─── GET /financeiro/caixa — histórico de fechamento de caixa (D-59) ──────────

class CaixaDiaOut(BaseModel):
    date: str
    opening_balance: float
    cash_received: float
    change_given: float
    cash_expenses: float
    cash_total: float
    withdrawal: float
    closing_balance: float
    other_methods_received: float
    other_methods_expenses: float


class CaixaHistoricoOut(BaseModel):
    month: str
    days: list[CaixaDiaOut]


@router.get("/caixa", response_model=CaixaHistoricoOut)
async def get_financeiro_caixa(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    month: str = Query(..., description="Mês no formato YYYY-MM"),
) -> CaixaHistoricoOut:
    """Histórico de fechamento de caixa diário migrado da Trinks (D-59).

    Só existe para o período importado (hist. jan-jul/2026); não é um caixa
    vivo (abrir/fechar em tempo real) — ver `CLAUDE.md`.
    """
    await _require_manager(db, current_user)
    date_from, date_to = _month_range(month)

    rows = (
        await db.execute(
            select(CashDailyClosing)
            .where(CashDailyClosing.closing_date >= date_from)
            .where(CashDailyClosing.closing_date <= date_to)
            .order_by(CashDailyClosing.closing_date)
        )
    ).scalars().all()

    return CaixaHistoricoOut(
        month=month,
        days=[
            CaixaDiaOut(
                date=r.closing_date.isoformat(),
                opening_balance=float(r.opening_balance),
                cash_received=float(r.cash_received),
                change_given=float(r.change_given),
                cash_expenses=float(r.cash_expenses),
                cash_total=float(r.cash_total),
                withdrawal=float(r.withdrawal),
                closing_balance=float(r.closing_balance),
                other_methods_received=float(r.other_methods_received),
                other_methods_expenses=float(r.other_methods_expenses),
            )
            for r in rows
        ],
    )


# ─── GET /financeiro/dre — DRE mensal migrado da Trinks (D-65) ────────────────

class DreMesOut(BaseModel):
    month: str  # YYYY-MM
    receita: float
    despesa: float
    resultado: float
    margem_pct: float
    despesa_por_subgrupo: dict[str, float]


class DreSerieOut(BaseModel):
    inicio: Optional[str]
    fim: Optional[str]
    months: list[DreMesOut]
    receita_total: float
    despesa_total: float
    resultado_total: float


def _month_first(month: Optional[str]) -> Optional[date]:
    """'YYYY-MM' → 1º dia do mês. None/'' → None. Formato inválido → 422."""
    if not month:
        return None
    if not _MONTH_RE.match(month):
        raise HTTPException(422, "Mês inválido. Use o formato YYYY-MM.")
    return date(int(month[:4]), int(month[5:7]), 1)


@router.get("/dre", response_model=DreSerieOut)
async def get_financeiro_dre(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    inicio: Annotated[Optional[str], Query(description="Mês inicial YYYY-MM (opcional)")] = None,
    fim: Annotated[Optional[str], Query(description="Mês final YYYY-MM (opcional)")] = None,
) -> DreSerieOut:
    """Série mensal do DRE migrado da Trinks (competência): receita, despesa (com
    quebra por subgrupo), resultado e margem. Histórico só do período importado —
    ver `dre_monthly_lines`. Complementar a `/caixa` (recebimento); não reconcilia 1:1.
    """
    await _require_manager(db, current_user)
    date_from = _month_first(inicio)
    date_to = _month_first(fim)

    q = (
        select(
            DreMonthlyLine.competence_month,
            DreMonthlyLine.section,
            DreMonthlyLine.subgroup,
            func.sum(DreMonthlyLine.amount).label("total"),
        )
        .group_by(
            DreMonthlyLine.competence_month,
            DreMonthlyLine.section,
            DreMonthlyLine.subgroup,
        )
        .order_by(DreMonthlyLine.competence_month)
    )
    if date_from is not None:
        q = q.where(DreMonthlyLine.competence_month >= date_from)
    if date_to is not None:
        q = q.where(DreMonthlyLine.competence_month <= date_to)

    rows = (await db.execute(q)).all()

    by_month: dict[date, dict] = {}
    for r in rows:
        m = by_month.setdefault(
            r.competence_month,
            {"receita": Decimal("0"), "despesa": Decimal("0"), "subgroups": {}},
        )
        if r.section == "receita":
            m["receita"] += r.total
        else:
            m["despesa"] += r.total
            key = r.subgroup or "outros"
            m["subgroups"][key] = m["subgroups"].get(key, Decimal("0")) + r.total

    months: list[DreMesOut] = []
    receita_total = despesa_total = Decimal("0")
    for month_date in sorted(by_month):
        m = by_month[month_date]
        receita, despesa = m["receita"], m["despesa"]
        resultado = receita - despesa
        receita_total += receita
        despesa_total += despesa
        margem = (resultado / receita * 100) if receita else Decimal("0")
        months.append(
            DreMesOut(
                month=month_date.strftime("%Y-%m"),
                receita=float(receita),
                despesa=float(despesa),
                resultado=float(resultado),
                margem_pct=round(float(margem), 2),
                despesa_por_subgrupo={k: float(v) for k, v in sorted(m["subgroups"].items())},
            )
        )

    return DreSerieOut(
        inicio=inicio or None,
        fim=fim or None,
        months=months,
        receita_total=float(receita_total),
        despesa_total=float(despesa_total),
        resultado_total=float(receita_total - despesa_total),
    )


# ─── Despesas (CRUD) ──────────────────────────────────────────────────────────

class ExpenseCreateIn(BaseModel):
    category: str = Field(..., min_length=2, max_length=80, description="Nome da categoria (criada se não existir)")
    amount: float = Field(..., gt=0)
    month: str = Field(..., description="Mês de competência YYYY-MM")
    note: Optional[str] = Field(None, max_length=300)


@router.post("/despesas", response_model=ExpenseOut, status_code=http_status.HTTP_201_CREATED)
async def criar_despesa(
    body: ExpenseCreateIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ExpenseOut:
    await _require_manager(db, current_user)
    competence, _ = _month_range(body.month)

    category_name = body.category.strip()
    category = (
        await db.execute(
            select(ExpenseCategory).where(
                func.lower(ExpenseCategory.name) == category_name.lower()
            )
        )
    ).scalar_one_or_none()
    if category is None:
        category = ExpenseCategory(
            organization_id=current_user.organization_id, name=category_name
        )
        db.add(category)
        await db.flush()

    unit = (
        await db.execute(
            select(Unit).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1)
        )
    ).scalar_one_or_none()
    if unit is None:
        raise HTTPException(409, "Organização sem unidade cadastrada.")

    expense = Expense(
        organization_id=current_user.organization_id,
        unit_id=unit.id,
        category_id=category.id,
        amount=Decimal(str(body.amount)),
        competence_month=competence,
        note=body.note or None,
    )
    db.add(expense)
    await db.flush()

    return ExpenseOut(
        id=expense.id,
        category=category.name,
        amount=float(expense.amount),
        competence_month=expense.competence_month.isoformat(),
        note=expense.note,
    )


@router.delete("/despesas/{expense_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def remover_despesa(
    expense_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    await _require_manager(db, current_user)
    expense = (
        await db.execute(select(Expense).where(Expense.id == expense_id))
    ).scalar_one_or_none()
    if expense is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Despesa não encontrada."
        )
    await db.delete(expense)
    await db.flush()


# ─── Export CSV ───────────────────────────────────────────────────────────────

def _csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    """CSV pt-BR (separador ';', decimal vírgula, BOM para Excel)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([
            f"{v:.2f}".replace(".", ",") if isinstance(v, float) else v
            for v in row
        ])
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/comissoes.csv")
async def export_comissoes_csv(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    month: str = Query(..., description="Mês no formato YYYY-MM"),
) -> Response:
    """Relatório de comissões para repasse — uma linha por barbeiro."""
    await _require_manager(db, current_user)
    date_from, date_to = _month_range(month)

    barber_rows = await barber_revenue_rows(db, date_from, date_to)
    rows = [
        [
            r.name,
            r.appt_count,
            float(r.revenue),
            f"{float(r.commission_pct) * 100:.0f}%",
            float(Decimal(str(r.revenue)) * r.commission_pct),
        ]
        for r in barber_rows
    ]
    total_rev = sum(float(r.revenue) for r in barber_rows)
    total_com = sum(float(Decimal(str(r.revenue)) * r.commission_pct) for r in barber_rows)
    rows.append(["TOTAL", sum(r.appt_count for r in barber_rows), total_rev, "", total_com])

    return _csv_response(
        f"comissoes-{month}.csv",
        ["Barbeiro", "Atendimentos", "Receita (R$)", "Comissão (%)", "Comissão (R$)"],
        rows,
    )


@router.get("/export/faturamento.csv")
async def export_faturamento_csv(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    month: str = Query(..., description="Mês no formato YYYY-MM"),
) -> Response:
    """Faturamento diário do mês — uma linha por dia com atendimento concluído."""
    await _require_manager(db, current_user)
    date_from, date_to = _month_range(month)

    daily_rows = (
        await db.execute(
            select(
                local_date(Appointment.start_at).label("day"),
                func.count(Appointment.id.distinct()).label("cnt"),
                func.coalesce(func.sum(AppointmentItem.price_charged), 0).label("rev"),
            )
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .where(local_date(Appointment.start_at) >= date_from)
            .where(local_date(Appointment.start_at) <= date_to)
            .group_by(local_date(Appointment.start_at))
            .order_by(local_date(Appointment.start_at))
        )
    ).all()

    rows = [
        [r.day.strftime("%d/%m/%Y"), r.cnt, float(r.rev)]
        for r in daily_rows
    ]
    rows.append([
        "TOTAL",
        sum(r.cnt for r in daily_rows),
        sum(float(r.rev) for r in daily_rows),
    ])

    return _csv_response(
        f"faturamento-{month}.csv",
        ["Data", "Atendimentos concluídos", "Receita (R$)"],
        rows,
    )
