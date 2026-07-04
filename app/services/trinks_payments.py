"""Importador do relatório "Pagamentos/Estornos" da Trinks (histórico analítico).

O relatório traz uma linha por pagamento/troco por comanda, com tipo e forma de
pagamento, valor, taxa da operadora (desconto, tipicamente negativo), líquido a
receber e conta financeira. Este módulo importa isso em `payment_transactions`
(migration 0035) — histórico ANALÍTICO, sem vínculo a `appointments`/`payments`
(ver D-63). Serve a relatórios de mix de formas de pagamento, custo de cartão e
recebíveis.

CSV ISO-8859-1 (latin-1) ou UTF-8, `;` como separador (mesmo `_read_rows` do
`trinks_import`). Localiza a tabela pelo cabeçalho (contém "valor pago" e "forma
de pagamento").

Idempotência por **substituição de período**: no commit, apaga as linhas `trinks`
cujo `movement_date` cai no intervalo coberto pelo arquivo e reinsere. Re-rodar o
mesmo arquivo converge ao mesmo estado; reexportar um período corrigido o
substitui. Não há chave natural única (pode haver pagamentos idênticos no mesmo
dia), por isso não se usa upsert por linha. Parte pura (`parse_payments`) +
persistência (`import_payments`).
⚠️ Arquivo cru é PII/financeiro — nunca versionar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trinks_import import _read_rows
from models import PaymentTransaction


@dataclass
class ParsedPayment:
    movement_date: date
    service_date: Optional[date]
    expected_receipt_date: Optional[date]
    payment_type: str
    payment_method: str
    installment: Optional[str]
    anticipated: bool
    entry_type: str
    comanda: Optional[str]
    amount_paid: Decimal
    operator_discount_pct: Optional[Decimal]
    operator_discount_amount: Decimal
    amount_to_receive: Decimal
    account: Optional[str]


@dataclass
class PaymentsParseReport:
    total_rows: int = 0
    parsed: int = 0
    skipped_no_date: int = 0

    def as_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "parsed": self.parsed,
            "skipped_no_date": self.skipped_no_date,
        }


@dataclass
class PaymentsImportReport:
    dry_run: bool
    range_start: Optional[date] = None
    range_end: Optional[date] = None
    removed_existing: int = 0
    inserted: int = 0
    sum_amount_paid: Decimal = field(default_factory=lambda: Decimal("0"))
    sum_amount_to_receive: Decimal = field(default_factory=lambda: Decimal("0"))
    sum_operator_discount: Decimal = field(default_factory=lambda: Decimal("0"))

    def as_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "range_start": self.range_start.isoformat() if self.range_start else None,
            "range_end": self.range_end.isoformat() if self.range_end else None,
            "removed_existing": self.removed_existing,
            "inserted": self.inserted,
            "sum_amount_paid": str(self.sum_amount_paid),
            "sum_amount_to_receive": str(self.sum_amount_to_receive),
            "sum_operator_discount": str(self.sum_operator_discount),
        }


def _parse_amount(v: str) -> Decimal:
    """Moeda BR → Decimal. Preserva sinal (desconto de operadora vem negativo)."""
    v = (v or "").strip().replace("R$", "").replace(" ", "")
    v = v.replace(".", "").replace(",", ".")
    if not v or v in ("-", "+"):
        return Decimal("0.00")
    try:
        return Decimal(v)
    except InvalidOperation:
        return Decimal("0.00")


def _parse_amount_opt(v: str) -> Optional[Decimal]:
    """Como `_parse_amount`, mas devolve None para célula vazia (percentual ausente)."""
    if not (v or "").strip():
        return None
    return _parse_amount(v)


def _parse_date(v: str) -> Optional[date]:
    v = (v or "").strip()
    if not v:
        return None
    # tolera hora anexa ("05/01/2026 14:30")
    v = v.split(" ")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _clean(v: str) -> Optional[str]:
    v = (v or "").strip()
    return v or None


def parse_payments(
    source: str | Path | bytes,
) -> tuple[list[ParsedPayment], PaymentsParseReport]:
    rows = _read_rows(source)
    report = PaymentsParseReport()

    hidx = None
    for i, row in enumerate(rows):
        low = [c.strip().lower() for c in row]
        if "valor pago" in low and "forma de pagamento" in low:
            hidx = i
            break
    if hidx is None:
        return [], report

    header = [c.strip().lower() for c in rows[hidx]]

    def col(name: str) -> int:
        """Índice por match EXATO do nome (as colunas 'Data …' são ambíguas por prefixo)."""
        n = name.strip().lower()
        for j, h in enumerate(header):
            if h == n:
                return j
        return -1

    i_mov = col("data movimentação")
    i_serv = col("data atendimento/venda")
    i_recv = col("data prevista recebimento")
    i_ptype = col("tipo de forma de pagamento")
    i_pmethod = col("forma de pagamento")
    i_parcela = col("parcela")
    i_antec = col("antecipada")
    i_tipo = col("tipo")
    i_comanda = col("comanda")
    i_paid = col("valor pago")
    i_disc_pct = col("percentual de desconto da operadora")
    i_disc_amt = col("valor de desconto da operadora (r$)")
    i_receive = col("valor a ser recebido")
    i_account = col("conta financeira")

    def cell(row: list[str], i: int) -> str:
        return row[i].strip() if 0 <= i < len(row) else ""

    out: list[ParsedPayment] = []
    for row in rows[hidx + 1 :]:
        if not any(c.strip() for c in row):
            continue
        report.total_rows += 1
        # chave do período: data da movimentação; cai para a data do atendimento.
        movement = _parse_date(cell(row, i_mov)) or _parse_date(cell(row, i_serv))
        if movement is None:
            report.skipped_no_date += 1
            continue
        out.append(
            ParsedPayment(
                movement_date=movement,
                service_date=_parse_date(cell(row, i_serv)),
                expected_receipt_date=_parse_date(cell(row, i_recv)),
                payment_type=cell(row, i_ptype),
                payment_method=cell(row, i_pmethod),
                installment=_clean(cell(row, i_parcela)),
                anticipated=cell(row, i_antec).lower() == "sim",
                entry_type=cell(row, i_tipo) or "Pagamento",
                comanda=_clean(cell(row, i_comanda)),
                amount_paid=_parse_amount(cell(row, i_paid)),
                operator_discount_pct=_parse_amount_opt(cell(row, i_disc_pct)),
                operator_discount_amount=_parse_amount(cell(row, i_disc_amt)),
                amount_to_receive=_parse_amount(cell(row, i_receive)),
                account=_clean(cell(row, i_account)),
            )
        )

    report.parsed = len(out)
    return out, report


async def import_payments(
    session: AsyncSession,
    org_id: int,
    rows: list[ParsedPayment],
    *,
    dry_run: bool = True,
) -> PaymentsImportReport:
    report = PaymentsImportReport(dry_run=dry_run)
    if not rows:
        return report

    dates = [r.movement_date for r in rows]
    report.range_start = min(dates)
    report.range_end = max(dates)
    report.inserted = len(rows)
    report.sum_amount_paid = sum((r.amount_paid for r in rows), Decimal("0"))
    report.sum_amount_to_receive = sum((r.amount_to_receive for r in rows), Decimal("0"))
    report.sum_operator_discount = sum(
        (r.operator_discount_amount for r in rows), Decimal("0")
    )

    # Quantas linhas 'trinks' já ocupam o intervalo (serão substituídas).
    existing = (
        await session.execute(
            select(func.count())
            .select_from(PaymentTransaction)
            .where(
                PaymentTransaction.organization_id == org_id,
                PaymentTransaction.source == "trinks",
                PaymentTransaction.movement_date >= report.range_start,
                PaymentTransaction.movement_date <= report.range_end,
            )
        )
    ).scalar_one()
    report.removed_existing = int(existing)

    if dry_run:
        return report

    # Substituição do período: apaga as 'trinks' do intervalo e reinsere (idempotente).
    await session.execute(
        delete(PaymentTransaction).where(
            PaymentTransaction.organization_id == org_id,
            PaymentTransaction.source == "trinks",
            PaymentTransaction.movement_date >= report.range_start,
            PaymentTransaction.movement_date <= report.range_end,
        )
    )
    session.add_all(
        [
            PaymentTransaction(
                organization_id=org_id,
                movement_date=r.movement_date,
                service_date=r.service_date,
                expected_receipt_date=r.expected_receipt_date,
                payment_type=r.payment_type,
                payment_method=r.payment_method,
                installment=r.installment,
                anticipated=r.anticipated,
                entry_type=r.entry_type,
                comanda=r.comanda,
                amount_paid=r.amount_paid,
                operator_discount_pct=r.operator_discount_pct,
                operator_discount_amount=r.operator_discount_amount,
                amount_to_receive=r.amount_to_receive,
                account=r.account,
                source="trinks",
            )
            for r in rows
        ]
    )
    await session.flush()
    return report
