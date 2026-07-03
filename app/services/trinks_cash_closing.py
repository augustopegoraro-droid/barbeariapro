"""Importador do FECHAMENTO DE CAIXA DIÁRIO exportado da Trinks.

O relatório "Movimentação Financeira" da Trinks traz duas tabelas no mesmo
arquivo: (1) pagamentos por comanda — fora de escopo aqui, exigiria agendamentos
casados; (2) "Resumo de Movimentação de Entradas e Saídas" — um fechamento por
dia (abertura/recebido/troco/despesas/sangria/saldo), que é o que este módulo
importa em `cash_daily_closings` (migration 0026). Ainda não existe módulo de
Caixa (abrir/fechar em tempo real); isto é só o histórico migrado.

CSV ISO-8859-1 (latin-1) ou UTF-8, `;` como separador (mesmo `_read_rows` do
`trinks_import`). Localiza a tabela pelo cabeçalho (contém "data" e "abertura do
caixa"); ignora a linha de rodapé "Total período" (1ª coluna vazia).

Idempotente: upsert por `(organization_id, closing_date)` — re-rodar atualiza o
mesmo dia em vez de duplicar. Parte pura (`parse_cash_closings`) + persistência
(`import_cash_closings`).
⚠️ Arquivo cru é PII/financeiro — nunca versionar.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trinks_import import _read_rows
from models import CashDailyClosing


@dataclass
class ParsedCashClosing:
    closing_date: date
    opening_balance: Decimal
    cash_received: Decimal
    change_given: Decimal
    cash_expenses: Decimal
    cash_total: Decimal
    withdrawal: Decimal
    closing_balance: Decimal
    other_methods_received: Decimal
    other_methods_expenses: Decimal
    opening_history: Optional[str]


@dataclass
class CashClosingParseReport:
    total_rows: int = 0
    parsed: int = 0
    no_date: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CashClosingImportReport:
    dry_run: bool
    created: int = 0
    updated: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _parse_amount(v: str) -> Decimal:
    v = (v or "").strip().replace(".", "").replace(",", ".")
    if not v:
        return Decimal("0.00")
    try:
        return Decimal(v)
    except InvalidOperation:
        return Decimal("0.00")


def _parse_date(v: str) -> Optional[date]:
    v = (v or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def parse_cash_closings(
    source: str | Path | bytes,
) -> tuple[list[ParsedCashClosing], CashClosingParseReport]:
    rows = _read_rows(source)
    report = CashClosingParseReport()

    hidx = None
    for i, row in enumerate(rows):
        low = [c.strip().lower() for c in row]
        if "data" in low and any("abertura do caixa" in c for c in low):
            hidx = i
            break
    if hidx is None:
        return [], report

    header = [c.strip().lower() for c in rows[hidx]]

    def col(*names: str) -> int:
        for n in names:
            for j, h in enumerate(header):
                if h == n or h.startswith(n):
                    return j
        return -1

    i_data = col("data")
    i_abertura = col("abertura do caixa")
    i_recebido_dinheiro = col("recebido em dinheiro")
    i_troco = col("troco")
    i_despesas_dinheiro = col("despesas pagas (dinheiro)")
    i_total_dinheiro = col("total em dinheiro")
    i_sangria = col("sangria")
    i_saldo = col("saldo do caixa")
    i_recebido_outras = col("recebido em outras formas")
    i_despesas_outras = col("despesas pagas em outras formas")
    i_historico = col("historico de abertura de caixa", "histórico de abertura de caixa")

    def cell(row: list[str], i: int) -> str:
        return row[i].strip() if 0 <= i < len(row) else ""

    out: list[ParsedCashClosing] = []
    for row in rows[hidx + 1 :]:
        if not any(c.strip() for c in row):
            continue
        # rodapé "Total período": 1ª coluna (data) vazia — não é um dia real.
        if not cell(row, i_data):
            continue
        report.total_rows += 1
        closing_date = _parse_date(cell(row, i_data))
        if closing_date is None:
            report.no_date += 1
            continue
        out.append(
            ParsedCashClosing(
                closing_date=closing_date,
                opening_balance=_parse_amount(cell(row, i_abertura)),
                cash_received=_parse_amount(cell(row, i_recebido_dinheiro)),
                change_given=_parse_amount(cell(row, i_troco)),
                cash_expenses=_parse_amount(cell(row, i_despesas_dinheiro)),
                cash_total=_parse_amount(cell(row, i_total_dinheiro)),
                withdrawal=_parse_amount(cell(row, i_sangria)),
                closing_balance=_parse_amount(cell(row, i_saldo)),
                other_methods_received=_parse_amount(cell(row, i_recebido_outras)),
                other_methods_expenses=_parse_amount(cell(row, i_despesas_outras)),
                opening_history=cell(row, i_historico) or None,
            )
        )

    report.parsed = len(out)
    return out, report


async def import_cash_closings(
    session: AsyncSession,
    org_id: int,
    rows: list[ParsedCashClosing],
    *,
    dry_run: bool = True,
) -> CashClosingImportReport:
    report = CashClosingImportReport(dry_run=dry_run)

    existing: dict[date, CashDailyClosing] = {
        row.closing_date: row
        for row in (
            await session.execute(
                select(CashDailyClosing).where(
                    CashDailyClosing.organization_id == org_id
                )
            )
        ).scalars()
    }

    for r in rows:
        current = existing.get(r.closing_date)
        if current is not None:
            report.updated += 1
            if dry_run:
                continue
            current.opening_balance = r.opening_balance
            current.cash_received = r.cash_received
            current.change_given = r.change_given
            current.cash_expenses = r.cash_expenses
            current.cash_total = r.cash_total
            current.withdrawal = r.withdrawal
            current.closing_balance = r.closing_balance
            current.other_methods_received = r.other_methods_received
            current.other_methods_expenses = r.other_methods_expenses
            current.opening_history = r.opening_history
            continue

        report.created += 1
        if dry_run:
            continue
        session.add(
            CashDailyClosing(
                organization_id=org_id,
                closing_date=r.closing_date,
                opening_balance=r.opening_balance,
                cash_received=r.cash_received,
                change_given=r.change_given,
                cash_expenses=r.cash_expenses,
                cash_total=r.cash_total,
                withdrawal=r.withdrawal,
                closing_balance=r.closing_balance,
                other_methods_received=r.other_methods_received,
                other_methods_expenses=r.other_methods_expenses,
                opening_history=r.opening_history,
                source="trinks",
            )
        )

    if not dry_run:
        await session.flush()
    return report
