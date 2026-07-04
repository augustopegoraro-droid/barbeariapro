"""Testes da sincronização de FIDELIDADE a partir do ranking da Trinks.

Duas camadas:
- Puros (sem DB): parsers de moeda/data BR, extração das colunas novas, cálculo dos pontos.
- Integração (sessão RLS direta, `rollback()` no fim): dry-run não grava; commit grava
  snapshot (status/última visita) + pontos no ledger; idempotência dos pontos.

Os de integração usam a fixture `auth_headers` só como *gate*: se o DB semeado estiver
indisponível, o login falha e o teste é pulado (mesmo critério dos demais de integração).
Nada é comitado (sempre `rollback`), então não há efeito colateral nem disparo de mensagens.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, set_current_org
from app.services.loyalty import DEFAULT_POINTS_PER_BRL, DEFAULT_POINTS_PER_VISIT
from app.services.trinks_ranking import (
    RankingRow,
    _parse_brl,
    _parse_date,
    _seed_points,
    _SEED_REASON,
    parse_ranking,
    sync_loyalty_from_ranking,
)
from models import Client
from models.enums import LoyaltyLedgerType, LoyaltyStatus
from models.loyalty import ClientLoyalty, LoyaltyPointEntry

FIXT = Path(__file__).parent / "fixtures" / "trinks"
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))


# ─────────────────────────── parsers puros (sem DB) ───────────────────────────


def test_parse_ranking_extrai_colunas_de_fidelidade():
    rows, rep = parse_ranking(FIXT / "ranking_sample.csv")
    assert rep.with_last_visit == 2
    joao, maria = rows
    assert joao.last_visit == date(2026, 6, 19)
    assert joao.visit_count == 27
    assert joao.total_spent == Decimal("7371.00")
    assert maria.last_visit == date(2026, 6, 30)
    assert maria.visit_count == 48
    assert maria.total_spent == Decimal("6153.00")


def test_parse_brl():
    assert _parse_brl("7.371,00") == Decimal("7371.00")
    assert _parse_brl("273,00") == Decimal("273.00")
    assert _parse_brl("1.234.567,89") == Decimal("1234567.89")
    assert _parse_brl("R$ 1.000,00") == Decimal("1000.00")
    assert _parse_brl("") == Decimal("0")
    assert _parse_brl("   ") == Decimal("0")
    assert _parse_brl("abc") == Decimal("0")  # inválido → 0, sem estourar


def test_parse_date():
    assert _parse_date("19/06/2026") == date(2026, 6, 19)
    assert _parse_date("19/06/2026 14:30") == date(2026, 6, 19)  # ignora a hora anexa
    assert _parse_date("2026-06-19") == date(2026, 6, 19)
    assert _parse_date("") is None
    assert _parse_date("sem data") is None


def test_seed_points():
    ppb, ppv = DEFAULT_POINTS_PER_BRL, DEFAULT_POINTS_PER_VISIT
    assert _seed_points(Decimal("7371.00"), 27, ppb, ppv) == 7641  # 7371 + 27×10
    assert _seed_points(Decimal("500.00"), 5, ppb, ppv) == 550
    assert _seed_points(Decimal("0"), 0, ppb, ppv) == 0
    assert _seed_points(Decimal("10.50"), 0, ppb, ppv) == 11  # HALF_UP
    assert _seed_points(Decimal("100"), -3, ppb, ppv) == 100  # visitas negativas não subtraem


# ─────────────────── integração (sessão RLS direta, sempre rollback) ───────────────────


def _unique_phone() -> str:
    return f"+5563{time.time_ns() % 1_000_000_000:09d}"


def _row(phone: str, *, last_visit: date, visits: int = 5, total: str = "500.00") -> RankingRow:
    return RankingRow(
        name="Cliente Teste Fidelidade",
        phone=phone,
        email=None,
        birth_date=None,
        last_visit=last_visit,
        visit_count=visits,
        total_spent=Decimal(total),
    )


@pytest.mark.asyncio
async def test_sync_dry_run_nao_grava(auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        phone = _unique_phone()
        c = Client(organization_id=SEED_ORG_ID, name="Teste DryRun", phone_e164=phone)
        session.add(c)
        await session.flush()
        try:
            rep = await sync_loyalty_from_ranking(
                session, SEED_ORG_ID, [_row(phone, last_visit=date(2025, 1, 1))], dry_run=True
            )
            assert rep.matched == 1
            assert rep.inativo == 1  # 01/01/2025 → >120 dias
            assert rep.points_total == 550
            assert rep.points_credited == 0  # dry-run não credita

            loyalty = (
                await session.execute(
                    select(ClientLoyalty).where(ClientLoyalty.client_id == c.id)
                )
            ).scalar_one_or_none()
            assert loyalty is None  # nada gravado
            led = (
                await session.execute(
                    select(LoyaltyPointEntry).where(LoyaltyPointEntry.client_id == c.id)
                )
            ).scalars().all()
            assert led == []
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_sync_commit_grava_status_e_pontos_idempotente(auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        phone = _unique_phone()
        c = Client(organization_id=SEED_ORG_ID, name="Teste Commit", phone_e164=phone)
        session.add(c)
        await session.flush()
        try:
            rep = await sync_loyalty_from_ranking(
                session, SEED_ORG_ID, [_row(phone, last_visit=date(2025, 1, 1))], dry_run=False
            )
            assert rep.matched == 1
            assert rep.inativo == 1
            assert rep.points_credited == 1

            loyalty = (
                await session.execute(
                    select(ClientLoyalty).where(ClientLoyalty.client_id == c.id)
                )
            ).scalar_one()
            assert loyalty.status == LoyaltyStatus.inativo
            assert loyalty.visit_count == 5
            assert loyalty.total_spent == Decimal("500.00")
            assert loyalty.last_visit_at is not None
            assert loyalty.points_balance == 550

            led = (
                await session.execute(
                    select(LoyaltyPointEntry).where(LoyaltyPointEntry.client_id == c.id)
                )
            ).scalars().all()
            assert len(led) == 1
            assert led[0].type == LoyaltyLedgerType.adjust
            assert led[0].points_delta == 550
            assert led[0].reason == _SEED_REASON

            # Idempotência: rodar de novo não duplica pontos nem cria 2º lançamento.
            rep2 = await sync_loyalty_from_ranking(
                session, SEED_ORG_ID, [_row(phone, last_visit=date(2025, 1, 1))], dry_run=False
            )
            assert rep2.points_credited == 0
            assert rep2.points_skipped_existing == 1
            led2 = (
                await session.execute(
                    select(LoyaltyPointEntry).where(LoyaltyPointEntry.client_id == c.id)
                )
            ).scalars().all()
            assert len(led2) == 1
            loyalty2 = (
                await session.execute(
                    select(ClientLoyalty).where(ClientLoyalty.client_id == c.id)
                )
            ).scalar_one()
            assert loyalty2.points_balance == 550
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_sync_status_ativo_para_visita_recente(auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        phone = _unique_phone()
        c = Client(organization_id=SEED_ORG_ID, name="Teste Ativo", phone_e164=phone)
        session.add(c)
        await session.flush()
        try:
            hoje = datetime.now(timezone.utc).date()
            rep = await sync_loyalty_from_ranking(
                session, SEED_ORG_ID, [_row(phone, last_visit=hoje, visits=1, total="50.00")],
                dry_run=False,
            )
            assert rep.ativo == 1
            loyalty = (
                await session.execute(
                    select(ClientLoyalty).where(ClientLoyalty.client_id == c.id)
                )
            ).scalar_one()
            assert loyalty.status == LoyaltyStatus.ativo
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_sync_telefone_inexistente_conta_not_found(auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        # DDD 00 nunca é real → não casa com nenhum cliente.
        rep = await sync_loyalty_from_ranking(
            session, SEED_ORG_ID, [_row("+550000000000", last_visit=date(2025, 1, 1))], dry_run=True
        )
        assert rep.matched == 0
        assert rep.not_found == 1
        await session.rollback()
