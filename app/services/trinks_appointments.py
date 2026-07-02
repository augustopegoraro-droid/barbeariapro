"""Importador de AGENDAMENTOS exportados da Trinks (onboarding de tenant).

Relatório latin-1/CRLF com preâmbulo (data range + gerado-em + linha vazia) e
cabeçalho na 4ª linha, `;`-delimitado. Colunas usadas: Data, Hora, Profissional,
Serviço, Duração, Cliente, Telefones, Email, Valor, Status.

Cada agendamento liga: cliente (por telefone; cria se novo) + profissional (por
nome) + serviço (via de-para Trinks→catálogo). Cria `Appointment` + `AppointmentItem`.

Parte pura (`parse_appointments`) sem DB; persistência (`import_appointments`) no org
escopado (RLS). ⚠️ Arquivo cru é PII — nunca versionar (ver .gitignore).
"""
from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import local_tz
from app.core.phone import normalize_phone
from models import Appointment, AppointmentItem, Barber, Client, Service, Unit
from models.enums import AppointmentStatus, ContactChannel

# ─── de-para de serviços: nome da Trinks (minúsculo) → nome no catálogo ──────────
_SERVICE_MAP: dict[str, str] = {
    "barba": "Barba",
    "corte masc. com taylor e thedy": "Corte Masculino",
    "corte masculino": "Corte Masculino",
    "corte e barba": "Corte + Barba",
    "corte infantil masculino": "Corte Infantil",
    "corte feminino": "Corte Feminino",
    "coloração / tonalização feminino": "Coloração",
    "escova simples": "Escova",
    "mechas": "Mechas",
    "selagem masculino": "Selagem Masculina",
    "manicure": "Manicure e Pedicure",
    "sobrancelha com linha": "Sobrancelha",
}


@dataclass
class ParsedAppointment:
    start_utc: datetime
    duration_min: int
    barber_name: str            # cru (ex.: "THEDY")
    service_system: Optional[str]  # nome no catálogo (None se sem de-para)
    service_trinks: str
    client_name: str
    client_phone: Optional[str]  # E.164 ou None
    client_email: Optional[str]
    price: Decimal


@dataclass
class ParseReport:
    total_rows: int = 0
    parsed: int = 0
    cancelled_skipped: int = 0
    unmapped_service: int = 0
    bad_datetime: int = 0
    no_phone: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportReport:
    dry_run: bool
    created: int = 0
    clients_created: int = 0
    clients_matched: int = 0
    skipped_no_service: int = 0
    skipped_no_barber: int = 0
    skipped_no_phone: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


# ─── parsing ─────────────────────────────────────────────────────────────────────

def _read_rows(source: str | Path | bytes) -> list[list[str]]:
    raw = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = raw.decode("latin-1")
    return list(csv.reader(txt.splitlines(), delimiter=";"))


def _find_header(rows: list[list[str]]) -> Optional[int]:
    for i, row in enumerate(rows):
        low = [c.strip().lower() for c in row]
        if "data" in low and "hora" in low and "cliente" in low:
            return i
    return None


def _parse_duration(value: str) -> int:
    """'30 min', '1h e 30 min', '3h e 10 min' → minutos."""
    v = (value or "").lower()
    h = re.search(r"(\d+)\s*h", v)
    m = re.search(r"(\d+)\s*min", v)
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def _parse_price(value: str) -> Decimal:
    v = (value or "").strip().replace(".", "").replace(",", ".")
    if not v:
        return Decimal("0.00")
    try:
        return Decimal(v)
    except InvalidOperation:
        return Decimal("0.00")


def _clean(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return v or None


def parse_appointments(source: str | Path | bytes) -> tuple[list[ParsedAppointment], ParseReport]:
    rows = _read_rows(source)
    report = ParseReport()
    hidx = _find_header(rows)
    if hidx is None:
        return [], report
    header = [c.strip().lower() for c in rows[hidx]]

    def col(name: str) -> int:
        return header.index(name) if name in header else -1

    idx = {k: col(k) for k in (
        "data", "hora", "profissional", "serviço", "duração",
        "cliente", "telefones", "email", "valor", "status",
    )}

    def cell(row: list[str], key: str) -> str:
        i = idx.get(key, -1)
        return row[i] if 0 <= i < len(row) else ""

    tz = local_tz()
    out: list[ParsedAppointment] = []

    for row in rows[hidx + 1 :]:
        if not any(c.strip() for c in row):
            continue
        report.total_rows += 1

        if cell(row, "status").strip().lower() == "cancelado":
            report.cancelled_skipped += 1
            continue

        # data + hora → UTC
        d, h = cell(row, "data").strip(), cell(row, "hora").strip()
        try:
            naive = datetime.strptime(f"{d} {h}", "%d/%m/%Y %H:%M")
            start_utc = naive.replace(tzinfo=tz).astimezone(timezone.utc)
        except ValueError:
            report.bad_datetime += 1
            continue

        service_trinks = cell(row, "serviço").strip()
        service_system = _SERVICE_MAP.get(service_trinks.lower())
        if service_system is None:
            report.unmapped_service += 1
            # ainda emite (o relatório de import mostra), mas marcado None

        raw_phone = cell(row, "telefones").strip()
        phone: Optional[str] = None
        if raw_phone:
            try:
                phone = normalize_phone(raw_phone)
            except ValueError:
                phone = None
        if phone is None:
            report.no_phone += 1

        out.append(
            ParsedAppointment(
                start_utc=start_utc,
                duration_min=_parse_duration(cell(row, "duração")),
                barber_name=cell(row, "profissional").strip(),
                service_system=service_system,
                service_trinks=service_trinks,
                client_name=_clean(cell(row, "cliente")) or "(sem nome)",
                client_phone=phone,
                client_email=(_clean(cell(row, "email")) or None),
                price=_parse_price(cell(row, "valor")),
            )
        )

    report.parsed = len(out)
    return out, report


# ─── persistência ────────────────────────────────────────────────────────────────

async def import_appointments(
    session: AsyncSession,
    org_id: int,
    records: list[ParsedAppointment],
    *,
    dry_run: bool = True,
) -> ImportReport:
    report = ImportReport(dry_run=dry_run)

    unit_id = (
        await session.execute(
            select(Unit.id)
            .where(Unit.organization_id == org_id)
            .order_by(Unit.id)
            .limit(1)
        )
    ).scalar_one()

    barbers = {
        n.lower(): i
        for i, n in (await session.execute(select(Barber.id, Barber.name))).all()
    }
    services = {
        n.lower(): i
        for i, n in (await session.execute(select(Service.id, Service.name))).all()
    }
    clients: dict[str, int] = {
        p: i
        for i, p in (
            await session.execute(select(Client.id, Client.phone_e164))
        ).all()
    }

    next_num = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(display_number), 0) FROM appointments "
                "WHERE unit_id = :u"
            ),
            {"u": unit_id},
        )
    ).scalar_one()

    walkin_channel = ContactChannel.passante  # "Estabelecimento" (Trinks) = walk-in

    for rec in records:
        if not rec.service_system:
            report.skipped_no_service += 1
            continue
        service_id = services.get(rec.service_system.lower())
        if service_id is None:
            report.skipped_no_service += 1
            continue
        barber_id = barbers.get(rec.barber_name.lower())
        if barber_id is None:
            report.skipped_no_barber += 1
            continue
        if rec.client_phone is None:
            report.skipped_no_phone += 1
            continue

        client_id = clients.get(rec.client_phone)
        if client_id is None:
            report.clients_created += 1
            if not dry_run:
                client = Client(
                    organization_id=org_id,
                    name=rec.client_name,
                    phone_e164=rec.client_phone,
                    email=rec.client_email,
                    acquisition_channel=walkin_channel,
                )
                session.add(client)
                await session.flush()
                client_id = client.id
                clients[rec.client_phone] = client_id
        else:
            report.clients_matched += 1

        next_num += 1
        report.created += 1
        if dry_run:
            continue

        end_utc = rec.start_utc + _minutes(rec.duration_min)
        appt = Appointment(
            organization_id=org_id,
            unit_id=unit_id,
            client_id=client_id,
            display_number=next_num,
            start_at=rec.start_utc,
            end_at=end_utc,
            status=AppointmentStatus.agendado,
            booking_channel=walkin_channel,
            total_amount=rec.price,
        )
        session.add(appt)
        await session.flush()
        session.add(
            AppointmentItem(
                appointment_id=appt.id,
                service_id=service_id,
                barber_id=barber_id,
                price_charged=rec.price,
                duration_minutes=rec.duration_min or 30,
                position=1,
            )
        )

    if not dry_run:
        await session.flush()
    return report


def _minutes(n: int):
    from datetime import timedelta

    return timedelta(minutes=n or 30)
