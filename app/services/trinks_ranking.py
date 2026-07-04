"""Enriquecimento de clientes + sincronização de fidelidade a partir do RANKING da Trinks.

O ranking traz, por cliente com atividade no período, além de Email e Data de
Nascimento: **Último Atendimento**, **Visitas com pagamento no período** e **Total**
gasto. O arquivo de cadastro não tem nada disso — é o único lugar com o histórico de
visita. Este módulo tem dois usos independentes sobre o mesmo parser:

- `enrich_clients` — preenche lacunas de email/nascimento (nunca sobrescreve).
- `sync_loyalty_from_ranking` — **semeia a fidelidade** (`client_loyalty`): `last_visit_at`,
  `visit_count`, `total_spent` e o `status` derivado (ativo/em risco/inativo), além de
  creditar os PONTOS históricos no ledger (idempotente). É o bootstrap que destrava a
  campanha de reativação (que filtra `status IN (em_risco, inativo)`) e a visão de
  inativos — dados que, sem isto, só nasceriam ao concluir atendimentos pelo sistema.

  Semântica do bootstrap: os campos legados (visit_count/total_spent/last_visit) são a
  **verdade da Trinks até o cliente voltar**. Quando ele concluir um atendimento no
  sistema, `loyalty.recalculate` reescreve esses campos com os agregados do sistema
  (correto daí em diante) e SOMA os pontos novos ao seed — o ledger é append-only.

Relatório latin-1/CRLF com 3 linhas de preâmbulo e cabeçalho com "Posição";"Nome Cliente";
"Email";"Telefones";"Data de Nascimento";...;"Último Atendimento";"Visitas com pagamento
no período";...;"Total". ⚠️ Arquivo cru é PII — nunca versionar.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.phone import normalize_phone
from app.services import loyalty as loyalty_svc
from app.services.loyalty import (
    DEFAULT_POINTS_PER_BRL,
    DEFAULT_POINTS_PER_VISIT,
    compute_categoria,
    compute_nivel,
    compute_status,
)
from app.services.trinks_import import _read_rows  # leitor compartilhado (bytes/path)
from models import Client
from models.enums import LoyaltyLedgerType, LoyaltyStatus
from models.loyalty import ClientLoyalty, LoyaltyPointEntry, LoyaltyRule


@dataclass
class RankingRow:
    name: str
    phone: Optional[str]
    email: Optional[str]
    birth_date: Optional[date]
    # Histórico de fidelidade (usado só por `sync_loyalty_from_ranking`).
    last_visit: Optional[date] = None
    visit_count: int = 0
    total_spent: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class RankingParseReport:
    total_rows: int = 0
    parsed: int = 0
    no_phone: int = 0
    with_email: int = 0
    with_birth: int = 0
    with_last_visit: int = 0

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


def _parse_date(v: str) -> Optional[date]:
    """Data de atendimento — dd/mm/YYYY (aceita hora anexa, ignora)."""
    v = (v or "").strip()
    if not v:
        return None
    head = v.split()[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _parse_brl(v: str) -> Decimal:
    """Valor monetário no formato BR ('7.371,00' → 7371.00). Vazio/inválido → 0."""
    v = (v or "").strip().replace("R$", "").replace(" ", "")
    if not v:
        return Decimal("0")
    v = v.replace(".", "").replace(",", ".")  # milhar '.' fora, decimal ',' → '.'
    try:
        return Decimal(v)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_int(v: str) -> int:
    v = (v or "").strip()
    try:
        return int(v) if v else 0
    except ValueError:
        return 0


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

    def find(sub: str) -> int:
        for i, h in enumerate(header):
            if sub in h:
                return i
        return -1

    i_name, i_phone = col("nome cliente"), col("telefones")
    i_email, i_birth = col("email"), col("data de nascimento")
    # Busca por substring: tolera acento ("último") e sufixos ("...no período").
    i_last, i_visits, i_total = find("ltimo atendimento"), find("visitas"), find("total")

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

        last_visit = _parse_date(cell(row, i_last))
        if last_visit:
            report.with_last_visit += 1

        out.append(
            RankingRow(
                name=name,
                phone=phone,
                email=email,
                birth_date=birth,
                last_visit=last_visit,
                visit_count=_parse_int(cell(row, i_visits)),
                total_spent=_parse_brl(cell(row, i_total)),
            )
        )

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


# ─── sincronização de fidelidade (bootstrap a partir do ranking) ──────────────────

# Marcador do lançamento de pontos histórico — garante idempotência (não recreditar).
_SEED_REASON = "importação Trinks (fidelidade histórica)"


@dataclass
class LoyaltySyncReport:
    dry_run: bool
    matched: int = 0
    not_found: int = 0
    no_phone: int = 0
    ativo: int = 0
    em_risco: int = 0
    inativo: int = 0
    points_credited: int = 0
    points_skipped_existing: int = 0
    points_total: int = 0  # soma de pontos que seriam/foram creditados (dry-run inclusive)

    def as_dict(self) -> dict:
        return asdict(self)


def _seed_points(total_spent: Decimal, visit_count: int, ppb: Decimal, ppv: int) -> int:
    """Pontos históricos = round(total × points_per_brl) + visitas × points_per_visit."""
    base = (Decimal(str(total_spent or 0)) * ppb).to_integral_value(rounding=ROUND_HALF_UP)
    return int(base) + max(0, visit_count) * int(ppv)


_STATUS_FIELD = {
    LoyaltyStatus.ativo: "ativo",
    LoyaltyStatus.em_risco: "em_risco",
    LoyaltyStatus.inativo: "inativo",
}


async def sync_loyalty_from_ranking(
    session: AsyncSession,
    org_id: int,
    rows: list[RankingRow],
    *,
    dry_run: bool = True,
) -> LoyaltySyncReport:
    """Semeia `client_loyalty` (última visita + status + pontos) a partir do ranking.

    Casa por telefone com clientes já existentes (não cria cliente). Idempotente: os
    campos do snapshot são reescritos a cada rodada; os PONTOS só são creditados uma vez
    por cliente (marcador ``_SEED_REASON`` no ledger — re-rodar não duplica). Em
    ``dry_run`` apenas conta (não escreve rule/tiers/ledger/snapshot).
    """
    report = LoyaltySyncReport(dry_run=dry_run)

    existing = {
        c.phone_e164: c
        for c in (
            await session.execute(select(Client).where(Client.phone_e164.isnot(None)))
        ).scalars()
    }

    # Regra de pontos: lê a da org (se existir); senão usa os defaults. Só faz seed real
    # de rule/tiers (escrita) quando for gravar.
    rule = (
        await session.execute(
            select(LoyaltyRule).where(LoyaltyRule.organization_id == org_id)
        )
    ).scalar_one_or_none()
    if rule is None and not dry_run:
        rule = await loyalty_svc.get_or_seed_rule(org_id, session)
    ppb = rule.points_per_brl if rule else DEFAULT_POINTS_PER_BRL
    ppv = int(rule.points_per_visit) if rule else DEFAULT_POINTS_PER_VISIT
    tiers = await loyalty_svc.get_or_seed_tiers(org_id, session) if not dry_run else None

    for r in rows:
        if not r.phone:
            report.no_phone += 1
            continue
        client = existing.get(r.phone)
        if client is None:
            report.not_found += 1
            continue
        report.matched += 1

        last_visit_at = (
            datetime.combine(r.last_visit, time(12, 0), tzinfo=timezone.utc)
            if r.last_visit
            else None
        )
        status = compute_status(last_visit_at)
        setattr(report, _STATUS_FIELD[status], getattr(report, _STATUS_FIELD[status]) + 1)

        pts = _seed_points(r.total_spent, r.visit_count, ppb, ppv)
        report.points_total += pts

        if dry_run:
            continue

        # Upsert do snapshot legado (verdade da Trinks até o cliente voltar).
        loyalty = (
            await session.execute(
                select(ClientLoyalty).where(ClientLoyalty.client_id == client.id)
            )
        ).scalar_one_or_none()
        if loyalty is None:
            loyalty = ClientLoyalty(client_id=client.id, organization_id=org_id)
            session.add(loyalty)
        loyalty.last_visit_at = last_visit_at
        loyalty.visit_count = r.visit_count
        loyalty.total_spent = r.total_spent
        loyalty.status = status
        loyalty.nivel = compute_nivel(r.visit_count, r.total_spent)
        loyalty.categoria = compute_categoria(r.visit_count)
        loyalty.updated_at = datetime.now(timezone.utc)
        await session.flush()

        # Pontos históricos no ledger (uma única vez por cliente).
        if pts > 0:
            already = (
                await session.execute(
                    select(LoyaltyPointEntry.id)
                    .where(LoyaltyPointEntry.client_id == client.id)
                    .where(LoyaltyPointEntry.type == LoyaltyLedgerType.adjust)
                    .where(LoyaltyPointEntry.reason == _SEED_REASON)
                    .limit(1)
                )
            ).first()
            if already is None:
                await loyalty_svc._append_entry(
                    session,
                    org_id=org_id,
                    client_id=client.id,
                    type_=LoyaltyLedgerType.adjust,
                    delta=pts,
                    reason=_SEED_REASON,
                )
                report.points_credited += 1
            else:
                report.points_skipped_existing += 1
        # Materializa points_balance + tier do ledger (inclui saldo 0 → tier base).
        await loyalty_svc._sync_loyalty_row(org_id, client.id, session, tiers)

    if not dry_run:
        await session.flush()
    return report
