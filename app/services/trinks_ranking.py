"""Enriquecimento de clientes a partir do RANKING exportado da Trinks.

O ranking traz Email e Data de Nascimento de quem teve atividade no período — dados
que muitos clientes não tinham no export de cadastro. Aqui usamos o ranking só para
**preencher lacunas** (nunca sobrescrever): casa o cliente por telefone e, se o campo
estiver vazio, preenche email/nascimento.

Relatório latin-1/CRLF com 3 linhas de preâmbulo e cabeçalho com "Nome Cliente";
"Email";"Telefones";"Data de Nascimento". Parte pura (`parse_ranking`) + persistência
(`enrich_clients`). ⚠️ Arquivo cru é PII — nunca versionar.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.phone import normalize_phone
from app.services.trinks_import import _read_rows  # leitor compartilhado (bytes/path)
from models import Client


@dataclass
class RankingRow:
    name: str
    phone: Optional[str]
    email: Optional[str]
    birth_date: Optional[date]


@dataclass
class RankingParseReport:
    total_rows: int = 0
    parsed: int = 0
    no_phone: int = 0
    with_email: int = 0
    with_birth: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class EnrichReport:
    dry_run: bool
    matched: int = 0
    not_found: int = 0
    email_filled: int = 0
    birth_filled: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _parse_birth(v: str) -> Optional[date]:
    v = (v or "").strip()
    if not v:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def parse_ranking(source: str | Path | bytes) -> tuple[list[RankingRow], RankingParseReport]:
    rows = _read_rows(source)
    report = RankingParseReport()

    hidx = None
    for i, row in enumerate(rows):
        low = [c.strip().lower() for c in row]
        if "nome cliente" in low and any("telefone" in c for c in low):
            hidx = i
            break
    if hidx is None:
        return [], report

    header = [c.strip().lower() for c in rows[hidx]]

    def col(name: str) -> int:
        return header.index(name) if name in header else -1

    i_name, i_phone = col("nome cliente"), col("telefones")
    i_email, i_birth = col("email"), col("data de nascimento")

    def cell(row: list[str], i: int) -> str:
        return row[i].strip() if 0 <= i < len(row) else ""

    out: list[RankingRow] = []
    for row in rows[hidx + 1 :]:
        if not any(c.strip() for c in row):
            continue
        report.total_rows += 1
        name = cell(row, i_name)
        if not name:
            continue

        raw = cell(row, i_phone)
        phone: Optional[str] = None
        if raw:
            try:
                phone = normalize_phone(raw)
            except ValueError:
                phone = None
        if phone is None:
            report.no_phone += 1

        email = (cell(row, i_email) or "").lower() or None
        if email:
            report.with_email += 1
        birth = _parse_birth(cell(row, i_birth))
        if birth:
            report.with_birth += 1

        out.append(RankingRow(name=name, phone=phone, email=email, birth_date=birth))

    report.parsed = len(out)
    return out, report


async def enrich_clients(
    session: AsyncSession,
    org_id: int,
    rows: list[RankingRow],
    *,
    dry_run: bool = True,
) -> EnrichReport:
    """Preenche email/nascimento faltantes dos clientes (casa por telefone).

    Nunca sobrescreve valor existente. Em dry-run, só conta.
    """
    report = EnrichReport(dry_run=dry_run)

    # Índice: telefone → Client (com os campos que podem ser preenchidos).
    existing = {
        c.phone_e164: c
        for c in (
            await session.execute(
                select(Client).where(Client.phone_e164.isnot(None))
            )
        ).scalars()
    }

    for r in rows:
        if not r.phone:
            continue
        client = existing.get(r.phone)
        if client is None:
            report.not_found += 1
            continue
        report.matched += 1
        if r.email and not client.email:
            report.email_filled += 1
            if not dry_run:
                client.email = r.email
        if r.birth_date and not client.birth_date:
            report.birth_filled += 1
            if not dry_run:
                client.birth_date = r.birth_date

    if not dry_run:
        await session.flush()
    return report
