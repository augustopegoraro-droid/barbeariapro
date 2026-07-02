"""Importador de DÉBITOS (contas a receber) exportados da Trinks.

CSV `_LIMPO` (UTF-8/BOM ou latin-1), cabeçalho na 1ª linha:
`Cliente;Data;Hora;Profissional;Serviço;Tipo;Valor (R$)`. Grava em `client_debts`
(migration 0023). Casa o cliente por **nome** (o export não traz telefone); sem casar
(ou nome ambíguo), guarda `client_name` e deixa `client_id` nulo — o débito não se perde.

Idempotente: pula débito idêntico (nome+data+valor+tipo) já existente, então re-rodar
não duplica. Parte pura (`parse_debts`) + persistência (`import_debts`).
⚠️ Arquivo cru é PII — nunca versionar.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trinks_import import _read_rows
from models import Client, ClientDebt

_KIND_MAP = {
    "agendamento não pago": "agendamento_nao_pago",
    "agendamento nao pago": "agendamento_nao_pago",
    "fechamento com dívida deixada": "fechamento_com_divida",
    "fechamento com divida deixada": "fechamento_com_divida",
}


@dataclass
class ParsedDebt:
    client_name: str
    amount: Decimal
    debt_date: Optional[date]
    service_desc: Optional[str]
    professional: Optional[str]
    kind: str


@dataclass
class DebtParseReport:
    total_rows: int = 0
    parsed: int = 0
    no_name: int = 0
    total_amount: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class DebtImportReport:
    dry_run: bool
    created: int = 0
    client_matched: int = 0
    client_unmatched: int = 0   # nome não encontrado
    client_ambiguous: int = 0   # nome com >1 cliente → client_id nulo
    skipped_duplicate: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _norm_name(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


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


def _clean(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return v or None


def parse_debts(source: str | Path | bytes) -> tuple[list[ParsedDebt], DebtParseReport]:
    rows = _read_rows(source)
    report = DebtParseReport()

    hidx = None
    for i, row in enumerate(rows):
        low = [c.strip().lower() for c in row]
        if "cliente" in low and any("valor" in c for c in low):
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

    i_cli = col("cliente")
    i_data = col("data")
    i_prof = col("profissional")
    i_serv = col("serviço", "servico")
    i_tipo = col("tipo")
    i_val = col("valor")

    def cell(row: list[str], i: int) -> str:
        return row[i].strip() if 0 <= i < len(row) else ""

    out: list[ParsedDebt] = []
    for row in rows[hidx + 1 :]:
        if not any(c.strip() for c in row):
            continue
        report.total_rows += 1
        name = cell(row, i_cli)
        if not name:
            report.no_name += 1
            continue
        amount = _parse_amount(cell(row, i_val))
        tipo_raw = cell(row, i_tipo)
        kind = _KIND_MAP.get(tipo_raw.lower(), _norm_name(tipo_raw).replace(" ", "_"))
        out.append(
            ParsedDebt(
                client_name=name,
                amount=amount,
                debt_date=_parse_date(cell(row, i_data)),
                service_desc=_clean(cell(row, i_serv)),
                professional=_clean(cell(row, i_prof)),
                kind=kind,
            )
        )
        report.total_amount += float(amount)

    report.parsed = len(out)
    report.total_amount = round(report.total_amount, 2)
    return out, report


async def import_debts(
    session: AsyncSession,
    org_id: int,
    rows: list[ParsedDebt],
    *,
    dry_run: bool = True,
) -> DebtImportReport:
    report = DebtImportReport(dry_run=dry_run)

    # nome normalizado → [ids] (para casar; ambíguo se >1)
    name_index: dict[str, list[int]] = {}
    for cid, cname in (await session.execute(select(Client.id, Client.name))).all():
        name_index.setdefault(_norm_name(cname), []).append(cid)

    # assinaturas já existentes (idempotência): (nome_norm, data, valor)
    existing: set[tuple] = set()
    for cn, dt, amt in (
        await session.execute(
            select(ClientDebt.client_name, ClientDebt.debt_date, ClientDebt.amount)
        )
    ).all():
        existing.add((_norm_name(cn), dt, amt))

    for r in rows:
        sig = (_norm_name(r.client_name), r.debt_date, r.amount)
        if sig in existing:
            report.skipped_duplicate += 1
            continue
        existing.add(sig)

        ids = name_index.get(_norm_name(r.client_name), [])
        client_id: Optional[int] = None
        if len(ids) == 1:
            client_id = ids[0]
            report.client_matched += 1
        elif len(ids) > 1:
            report.client_ambiguous += 1  # deixa client_id nulo (não adivinha)
        else:
            report.client_unmatched += 1

        report.created += 1
        if dry_run:
            continue
        session.add(
            ClientDebt(
                organization_id=org_id,
                client_id=client_id,
                client_name=r.client_name,
                amount=r.amount,
                debt_date=r.debt_date,
                service_desc=r.service_desc,
                professional=r.professional,
                kind=r.kind,
                status="aberto",
                source="trinks",
            )
        )

    if not dry_run:
        await session.flush()
    return report
