"""Importador do "DRE" (Demonstrativo de Resultado) mensal da Trinks.

O relatório é uma MATRIZ: colunas = meses ("outubro / 2025" … "julho / 2026" +
"Total do Período"), linhas = itens agrupados por seção:

    RECEITAS                          <- cabeçalho de seção (sem valores)
      Serviços; 82.813,00; …          <- linha-folha
      Consumo de Pré-pago; -388,00; … <- contra-receita (negativa)
      …
    Total de Receitas; …             <- total (recomputado → ignorado)

    (-) DESPESAS                      <- cabeçalho de seção
      Despesas Fixas; 24.451,01; …   <- SUBTOTAL do subgrupo (recomputado → ignorado)
        Aluguel; 3.750,00; …         <- linha-folha (subgroup='fixa')
        …
      Despesas Variáveis / Pessoal / Impostos / Outros …
    Total de Despesas; …             <- total (ignorado)
    Resultado do Período; …          <- resultado (ignorado)

Guarda só as **linhas-folha** em `dre_monthly_lines`. Subgrupos de despesa são
detectados **estruturalmente**: o 1º item-com-valor após um cabeçalho/linha em
branco, dentro de DESPESAS, é o subtotal do subgrupo (define o subgrupo e é pulado).
Um **self-check** compara a soma recomputada de cada mês com os totais declarados
no próprio arquivo (vira um checksum contra erro de parse).

CSV latin-1/utf-8, ';' (reusa `_read_rows` do `trinks_import`). Parte pura
(`parse_dre`) + persistência (`import_dre`, idempotente por substituição dos meses
cobertos pelo arquivo).
⚠️ Arquivo cru é financeiro sensível — nunca versionar.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trinks_import import _read_rows
from models import DreMonthlyLine

_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# Rótulos de TOTAL (recomputados — nunca viram linha). Normalizados (sem acento, lower).
_TOTAL_LABELS = {
    "total de receitas",
    "total de despesas",
    "resultado do periodo",
    "resultado operacional",
    "resultado liquido",
    "lucro liquido",
}

# Subgrupos de despesa conhecidos → slug. Um subgrupo novo cai no slug genérico.
_SUBGROUP_SLUGS = {
    "despesas fixas": "fixa",
    "despesas variaveis": "variavel",
    "pessoal": "pessoal",
    "impostos": "impostos",
    "outros": "outros",
}

_CENT = Decimal("0.01")


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _norm(s: str) -> str:
    return _strip_accents((s or "").strip()).lower()


def _slug(s: str) -> str:
    return "_".join(_norm(s).split())


def _parse_amount(v: str) -> Decimal:
    """Moeda BR → Decimal. Preserva sinal (contra-receita vem negativa)."""
    v = (v or "").strip().replace("R$", "").replace(" ", "")
    v = v.replace(".", "").replace(",", ".")
    if not v or v in ("-", "+"):
        return Decimal("0.00")
    try:
        return Decimal(v)
    except InvalidOperation:
        return Decimal("0.00")


def _parse_month(cell: str) -> Optional[date]:
    """'outubro / 2025' → date(2025, 10, 1). Ignora 'Total do Período' e afins."""
    parts = [p.strip() for p in (cell or "").split("/")]
    if len(parts) != 2:
        return None
    month = _MONTHS.get(_norm(parts[0]))
    if month is None:
        return None
    try:
        year = int(parts[1])
    except ValueError:
        return None
    return date(year, month, 1)


@dataclass
class ParsedDreLine:
    competence_month: date
    section: str             # 'receita' | 'despesa'
    subgroup: Optional[str]  # despesa: slug do subgrupo; None p/ receita
    line_item: str
    amount: Decimal


@dataclass
class DreParseReport:
    months: list = field(default_factory=list)  # ["2025-10", …]
    lines_parsed: int = 0
    receita_total: Decimal = field(default_factory=lambda: Decimal("0"))
    despesa_total: Decimal = field(default_factory=lambda: Decimal("0"))
    resultado: Decimal = field(default_factory=lambda: Decimal("0"))
    checksum_mismatches: list = field(default_factory=list)  # meses onde recomputado != declarado

    @property
    def checksum_ok(self) -> bool:
        """Soma recomputada das folhas bate com os totais declarados no arquivo."""
        return not self.checksum_mismatches

    def as_dict(self) -> dict:
        return {
            "months": self.months,
            "lines_parsed": self.lines_parsed,
            "receita_total": str(self.receita_total),
            "despesa_total": str(self.despesa_total),
            "resultado": str(self.resultado),
            "checksum_ok": self.checksum_ok,
            "checksum_mismatches": self.checksum_mismatches,
        }


def parse_dre(
    source: str | Path | bytes,
) -> tuple[list[ParsedDreLine], DreParseReport]:
    rows = _read_rows(source)
    report = DreParseReport()

    # 1) achar o cabeçalho: 1ª coluna vazia + colunas-mês parseáveis à direita.
    hidx = None
    month_cols: list[tuple[int, date]] = []
    for i, row in enumerate(rows):
        if not row or (row[0] or "").strip():
            continue
        cols = [(j, _parse_month(row[j])) for j in range(1, len(row))]
        cols = [(j, m) for j, m in cols if m is not None]
        if cols:
            hidx, month_cols = i, cols
            break
    if hidx is None:
        return [], report

    def cell(row: list[str], j: int) -> str:
        return row[j].strip() if 0 <= j < len(row) else ""

    out: list[ParsedDreLine] = []
    computed: dict[date, dict] = {}   # mês -> {'receita','despesa'} recomputado das folhas
    declared: dict[date, dict] = {}   # mês -> {'receita','despesa','resultado'} do próprio arquivo

    section: Optional[str] = None
    subgroup: Optional[str] = None
    expect_subtotal = False

    for row in rows[hidx + 1:]:
        label = cell(row, 0)
        vals = [(m, _parse_amount(cell(row, j))) for j, m in month_cols]
        has_values = any(cell(row, j) for j, _ in month_cols)
        n = _norm(label)

        if not label and not has_values:          # linha em branco
            if section == "despesa":
                expect_subtotal = True             # próximo item-com-valor = novo subgrupo
            continue

        if not has_values:                         # cabeçalho de seção puro
            if "despesa" in n:
                section, subgroup, expect_subtotal = "despesa", None, True
            elif "receita" in n:
                section, subgroup, expect_subtotal = "receita", None, False
            continue

        if n in _TOTAL_LABELS:                     # total declarado — guarda p/ self-check, ignora
            key = "receita" if "receita" in n else "despesa" if "despesa" in n else "resultado"
            for m, amt in vals:
                declared.setdefault(m, {})[key] = amt
            expect_subtotal = False
            continue

        if section == "despesa" and expect_subtotal:   # subtotal do subgrupo
            subgroup = _SUBGROUP_SLUGS.get(n, _slug(label))
            expect_subtotal = False
            continue

        if section is None:                        # valor antes de qualquer seção (não deveria)
            continue

        # linha-folha: emite uma linha por mês com valor != 0
        for m, amt in vals:
            if amt == 0:
                continue
            out.append(
                ParsedDreLine(
                    competence_month=m,
                    section=section,
                    subgroup=subgroup if section == "despesa" else None,
                    line_item=label,
                    amount=amt,
                )
            )
            c = computed.setdefault(m, {"receita": Decimal("0"), "despesa": Decimal("0")})
            c[section] += amt

    months = sorted({ln.competence_month for ln in out})
    report.months = [m.strftime("%Y-%m") for m in months]
    report.lines_parsed = len(out)
    report.receita_total = sum((ln.amount for ln in out if ln.section == "receita"), Decimal("0"))
    report.despesa_total = sum((ln.amount for ln in out if ln.section == "despesa"), Decimal("0"))
    report.resultado = report.receita_total - report.despesa_total

    # self-check: recomputado por mês vs. totais declarados no arquivo
    for m in months:
        c = computed.get(m, {})
        d = declared.get(m, {})
        rec_c = c.get("receita", Decimal("0"))
        desp_c = c.get("despesa", Decimal("0"))
        diffs = []
        if "receita" in d and abs(rec_c - d["receita"]) > _CENT:
            diffs.append(["receita", str(rec_c), str(d["receita"])])
        if "despesa" in d and abs(desp_c - d["despesa"]) > _CENT:
            diffs.append(["despesa", str(desp_c), str(d["despesa"])])
        if "resultado" in d and abs((rec_c - desp_c) - d["resultado"]) > _CENT:
            diffs.append(["resultado", str(rec_c - desp_c), str(d["resultado"])])
        if diffs:
            report.checksum_mismatches.append({"month": m.strftime("%Y-%m"), "diffs": diffs})

    return out, report


@dataclass
class DreImportReport:
    dry_run: bool
    months: list = field(default_factory=list)
    removed_existing: int = 0
    inserted: int = 0
    receita_total: Decimal = field(default_factory=lambda: Decimal("0"))
    despesa_total: Decimal = field(default_factory=lambda: Decimal("0"))
    resultado: Decimal = field(default_factory=lambda: Decimal("0"))

    def as_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "months": self.months,
            "removed_existing": self.removed_existing,
            "inserted": self.inserted,
            "receita_total": str(self.receita_total),
            "despesa_total": str(self.despesa_total),
            "resultado": str(self.resultado),
        }


async def import_dre(
    session: AsyncSession,
    org_id: int,
    rows: list[ParsedDreLine],
    *,
    dry_run: bool = True,
) -> DreImportReport:
    report = DreImportReport(dry_run=dry_run)
    if not rows:
        return report

    months = sorted({r.competence_month for r in rows})
    report.months = [m.strftime("%Y-%m") for m in months]
    report.inserted = len(rows)
    report.receita_total = sum((r.amount for r in rows if r.section == "receita"), Decimal("0"))
    report.despesa_total = sum((r.amount for r in rows if r.section == "despesa"), Decimal("0"))
    report.resultado = report.receita_total - report.despesa_total

    # Quantas linhas 'trinks' já ocupam esses meses (serão substituídas).
    existing = (
        await session.execute(
            select(func.count())
            .select_from(DreMonthlyLine)
            .where(
                DreMonthlyLine.organization_id == org_id,
                DreMonthlyLine.source == "trinks",
                DreMonthlyLine.competence_month.in_(months),
            )
        )
    ).scalar_one()
    report.removed_existing = int(existing)

    if dry_run:
        return report

    # Substituição de período (por mês): apaga as 'trinks' dos meses do arquivo e reinsere.
    await session.execute(
        delete(DreMonthlyLine).where(
            DreMonthlyLine.organization_id == org_id,
            DreMonthlyLine.source == "trinks",
            DreMonthlyLine.competence_month.in_(months),
        )
    )
    session.add_all(
        [
            DreMonthlyLine(
                organization_id=org_id,
                competence_month=r.competence_month,
                section=r.section,
                subgroup=r.subgroup,
                line_item=r.line_item,
                amount=r.amount,
                source="trinks",
            )
            for r in rows
        ]
    )
    await session.flush()
    return report
