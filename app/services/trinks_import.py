"""Importador de clientes exportados da Trinks (onboarding de tenant).

O export de clientes da Trinks é um relatório **ISO-8859-1 (latin-1), CRLF**, com
um **preâmbulo de filtros** no topo e a tabela real começando na linha de
cabeçalho `"CPF";"Origem";"Nome";...` (27 colunas, delimitador ';').

Este módulo tem duas partes independentes:
- `parse_clients(path)` — parsing/mapeamento **puro** (sem DB), robusto a ordem de
  colunas (mapeia por nome de cabeçalho), encoding e preâmbulo. Deduplica por
  telefone dentro do arquivo.
- `import_clients(session, records, ...)` — persiste no org já escopado na sessão
  (RLS), com `dry_run` e dedup contra os clientes existentes.

⚠️ Os arquivos crus contêm PII (LGPD) — nunca versionar (ver `.gitignore`).
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.phone import normalize_phone
from models import Client
from models.enums import ContactChannel

# ─── mapeamento de canal de aquisição ───────────────────────────────────────────
# "Origem" / "Como nos conheceu" da Trinks → ContactChannel do sistema.
_CHANNEL_MAP: dict[str, ContactChannel] = {
    "instagram": ContactChannel.instagram,
    "google": ContactChannel.google,
    "indicação": ContactChannel.indicacao,
    "indicacao": ContactChannel.indicacao,
    "indicaçao": ContactChannel.indicacao,
    "balcão": ContactChannel.passante,
    "balcao": ContactChannel.passante,
    "passante": ContactChannel.passante,
    "whatsapp": ContactChannel.whatsapp,
    "whats": ContactChannel.whatsapp,
}

# Nomes de coluna esperados (casados case-insensitive, sem acento sensível).
_COL_NAME = "nome"
_COL_PHONE1 = "telefone 1"
_COL_PHONE2 = "telefone 2"
_COL_EMAIL = "e-mail"
_COL_BIRTH = "data de nascimento"
_COL_NOTES = "observações"
_COL_ORIGIN = "origem"
_COL_HOWKNOWN = "como nos conheceu"
_COL_INSTAGRAM = "instagram"


@dataclass
class ParsedClient:
    name: str
    phone_e164: Optional[str]
    email: Optional[str]
    birth_date: Optional[date]
    notes: Optional[str]
    acquisition_channel: Optional[ContactChannel]
    raw_phone: str = ""  # telefone original (p/ diagnóstico de inválidos)


@dataclass
class ParseReport:
    total_rows: int = 0
    importable: int = 0  # com nome + telefone válido, únicos no arquivo
    no_name: int = 0
    no_phone: int = 0
    invalid_phone: int = 0
    dup_in_file: int = 0
    with_email: int = 0
    with_birth: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportReport:
    dry_run: bool
    inserted: int = 0
    skipped_existing: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


# ─── parsing ─────────────────────────────────────────────────────────────────────

def _read_rows(path: str | Path) -> list[list[str]]:
    """Lê o CSV lidando com encoding (utf-8 → fallback latin-1) e ';' como sep."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    # csv.reader lida com CRLF e aspas (inclui quebras de linha dentro de campos).
    return list(csv.reader(text.splitlines(), delimiter=";"))


def _find_header(rows: list[list[str]]) -> Optional[int]:
    """Índice da linha de cabeçalho (contém 'nome' e 'telefone', tabela larga)."""
    for i, row in enumerate(rows):
        low = [c.strip().lower() for c in row]
        if len(row) >= 8 and _COL_NAME in low and any("telefone" in c for c in low):
            return i
    return None


def _parse_birth(value: str) -> Optional[date]:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _map_channel(*values: str) -> Optional[ContactChannel]:
    for v in values:
        key = (v or "").strip().lower()
        if not key:
            continue
        for token, channel in _CHANNEL_MAP.items():
            if token in key:
                return channel
    return None


def _clean(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    return v or None


def parse_clients(path: str | Path) -> tuple[list[ParsedClient], ParseReport]:
    """Lê e mapeia o export de clientes. Deduplica por telefone dentro do arquivo.

    Retorna (registros_importáveis, relatório). Só entram em `registros` os que têm
    nome + telefone válido e são únicos no arquivo; os demais são contabilizados no
    relatório (não silenciosamente descartados).
    """
    rows = _read_rows(path)
    report = ParseReport()
    header_idx = _find_header(rows)
    if header_idx is None:
        return [], report

    header = [c.strip().lower() for c in rows[header_idx]]

    def col(name: str) -> int:
        return header.index(name) if name in header else -1

    idx_name = col(_COL_NAME)
    idx_p1, idx_p2 = col(_COL_PHONE1), col(_COL_PHONE2)
    idx_email, idx_birth = col(_COL_EMAIL), col(_COL_BIRTH)
    idx_notes = col(_COL_NOTES)
    idx_origin, idx_how = col(_COL_ORIGIN), col(_COL_HOWKNOWN)
    idx_insta = col(_COL_INSTAGRAM)

    def cell(row: list[str], i: int) -> str:
        return row[i] if 0 <= i < len(row) else ""

    seen_phones: set[str] = set()
    out: list[ParsedClient] = []

    for row in rows[header_idx + 1 :]:
        if not any(c.strip() for c in row):
            continue  # linha vazia
        report.total_rows += 1

        name = _clean(cell(row, idx_name))
        if not name:
            report.no_name += 1
            continue

        raw_phone = cell(row, idx_p1).strip() or cell(row, idx_p2).strip()
        if not raw_phone:
            report.no_phone += 1
            continue
        try:
            phone = normalize_phone(raw_phone)
        except ValueError:
            report.invalid_phone += 1
            continue

        if phone in seen_phones:
            report.dup_in_file += 1
            continue
        seen_phones.add(phone)

        email = _clean(cell(row, idx_email))
        if email:
            email = email.lower()
            report.with_email += 1
        birth = _parse_birth(cell(row, idx_birth))
        if birth:
            report.with_birth += 1

        # Observações: junta obs livre + Instagram (quando houver).
        note_parts = []
        obs = _clean(cell(row, idx_notes))
        if obs:
            note_parts.append(obs)
        insta = _clean(cell(row, idx_insta))
        if insta:
            note_parts.append(f"Instagram: {insta}")
        notes = " | ".join(note_parts) or None

        channel = _map_channel(cell(row, idx_origin), cell(row, idx_how))

        out.append(
            ParsedClient(
                name=name,
                phone_e164=phone,
                email=email,
                birth_date=birth,
                notes=notes,
                acquisition_channel=channel,
                raw_phone=raw_phone,
            )
        )

    report.importable = len(out)
    return out, report


# ─── persistência ────────────────────────────────────────────────────────────────

async def import_clients(
    session: AsyncSession,
    org_id: int,
    records: list[ParsedClient],
    *,
    dry_run: bool = True,
) -> ImportReport:
    """Insere os clientes no org já escopado na sessão (RLS).

    Deduplica contra os telefones já existentes no org. Em `dry_run`, apenas conta
    (não adiciona nem commita). O commit fica a cargo do chamador (script).
    """
    report = ImportReport(dry_run=dry_run)

    existing: set[str] = set(
        (await session.execute(select(Client.phone_e164))).scalars().all()
    )

    for rec in records:
        if rec.phone_e164 in existing:
            report.skipped_existing += 1
            continue
        existing.add(rec.phone_e164)
        report.inserted += 1
        if dry_run:
            continue
        session.add(
            Client(
                organization_id=org_id,
                name=rec.name,
                phone_e164=rec.phone_e164,
                email=rec.email,
                birth_date=rec.birth_date,
                notes=rec.notes,
                acquisition_channel=rec.acquisition_channel,
            )
        )

    if not dry_run:
        await session.flush()
    return report
