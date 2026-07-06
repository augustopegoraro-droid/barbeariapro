"""Testes do import do DRE (Demonstrativo de Resultado) mensal da Trinks.

Duas camadas:
- Puros (sem DB): despivota os meses, detecta seções/subgrupos, preserva sinal das
  contra-receitas, pula zeros, descarta subtotais/totais e confere o self-check
  (soma recomputada == totais declarados no arquivo). Cobre também o caminho latin-1.
- Integração (sessão RLS direta, `rollback()` no fim): dry-run não grava; commit
  substitui os meses (delete + insert) e é idempotente.

A fixture `dre_sample.csv` é SINTÉTICA (nunca dados reais de T&T — o DRE é P&L
sensível). Os de integração usam `auth_headers` só como *gate*: sem DB semeado o
login falha e o teste é pulado. Nada é comitado (sempre `rollback`).
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, set_current_org
from app.services.trinks_dre import (
    _parse_amount,
    _parse_month,
    import_dre,
    parse_dre,
)
from models import DreMonthlyLine

FIXT = Path(__file__).parent / "fixtures" / "trinks"
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))

# Meses cobertos pela fixture.
_MONTHS = [date(2026, 3, 1), date(2026, 4, 1)]

_SUBTOTAL_TOTAL_LABELS = {
    "Despesas Fixas",
    "Pessoal",
    "Total de Receitas",
    "Total de Despesas",
    "Resultado do Período",
    "RECEITAS",
    "(-) DESPESAS",
}


# ─────────────────────────── parsers puros (sem DB) ───────────────────────────


def test_parse_amount_preserva_sinal():
    assert _parse_amount("1.000,00") == Decimal("1000.00")
    assert _parse_amount("-50,00") == Decimal("-50.00")  # contra-receita
    assert _parse_amount("0,00") == Decimal("0.00")
    assert _parse_amount("") == Decimal("0.00")
    assert _parse_amount("abc") == Decimal("0.00")  # inválido → 0, sem estourar


def test_parse_month():
    assert _parse_month("março / 2026") == date(2026, 3, 1)  # acento normalizado
    assert _parse_month("outubro / 2025") == date(2025, 10, 1)
    assert _parse_month("Total do Período") is None
    assert _parse_month("") is None


def test_parse_dre_totais_e_checksum():
    lines, rep = parse_dre(FIXT / "dre_sample.csv")

    assert rep.months == ["2026-03", "2026-04"]
    assert rep.lines_parsed == 11  # 6 (março) + 5 (abril; Consumo=0 pulado)
    assert rep.receita_total == Decimal("2500.00")
    assert rep.despesa_total == Decimal("1850.00")
    assert rep.resultado == Decimal("650.00")
    # self-check: recomputado bate com os totais declarados no arquivo
    assert rep.checksum_ok is True
    assert rep.checksum_mismatches == []
    assert rep.as_dict()["checksum_ok"] is True


def test_parse_dre_descarta_subtotais_e_totais():
    lines, _ = parse_dre(FIXT / "dre_sample.csv")
    rotulos = {ln.line_item for ln in lines}
    # subtotais de subgrupo e totais NUNCA viram linha (senão dupla contagem)
    assert rotulos.isdisjoint(_SUBTOTAL_TOTAL_LABELS)
    assert "Serviços" in rotulos
    assert "Aluguel" in rotulos
    assert "Salários" in rotulos


def test_parse_dre_secoes_subgrupos_e_sinal():
    lines, _ = parse_dre(FIXT / "dre_sample.csv")

    def find(item, month):
        return next(
            ln for ln in lines if ln.line_item == item and ln.competence_month == month
        )

    servicos = find("Serviços", date(2026, 3, 1))
    assert servicos.section == "receita"
    assert servicos.subgroup is None  # receita não tem subgrupo
    assert servicos.amount == Decimal("1000.00")

    consumo = [ln for ln in lines if ln.line_item == "Consumo de Pré-pago"]
    assert len(consumo) == 1  # abril = 0,00 → pulado (só março)
    assert consumo[0].amount == Decimal("-50.00")  # sinal preservado

    aluguel = find("Aluguel", date(2026, 3, 1))
    assert aluguel.section == "despesa"
    assert aluguel.subgroup == "fixa"

    salarios = find("Salários", date(2026, 3, 1))
    assert salarios.section == "despesa"
    assert salarios.subgroup == "pessoal"

    subgrupos = {ln.subgroup for ln in lines if ln.section == "despesa"}
    assert subgrupos == {"fixa", "pessoal"}


def test_parse_dre_latin1():
    """O real vem em latin-1; `_read_rows` cai de utf-8 p/ latin-1 sem perder acento."""
    raw = (FIXT / "dre_sample.csv").read_text(encoding="utf-8").encode("latin-1")
    lines, rep = parse_dre(raw)
    assert rep.lines_parsed == 11
    assert rep.checksum_ok is True
    assert any(ln.line_item == "Salários" and ln.subgroup == "pessoal" for ln in lines)


def test_parse_dre_vazio_nao_estoura():
    lines, rep = parse_dre(b"linha solta sem cabecalho\n")
    assert lines == []
    assert rep.lines_parsed == 0


# ─────────────────── integração (sessão RLS direta, sempre rollback) ───────────────────


async def _count_trinks_months(session, org, months) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(DreMonthlyLine)
            .where(
                DreMonthlyLine.organization_id == org,
                DreMonthlyLine.source == "trinks",
                DreMonthlyLine.competence_month.in_(months),
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_import_dre_dry_run_nao_grava(auth_headers):
    rows, _ = parse_dre(FIXT / "dre_sample.csv")
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        try:
            before = await _count_trinks_months(session, SEED_ORG_ID, _MONTHS)
            rep = await import_dre(session, SEED_ORG_ID, rows, dry_run=True)
            assert rep.inserted == 11
            assert rep.months == ["2026-03", "2026-04"]
            assert rep.receita_total == Decimal("2500.00")
            assert rep.despesa_total == Decimal("1850.00")
            after = await _count_trinks_months(session, SEED_ORG_ID, _MONTHS)
            assert after == before  # dry-run não gravou nada
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_import_dre_commit_substitui_periodo_idempotente(auth_headers):
    rows, _ = parse_dre(FIXT / "dre_sample.csv")
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        try:
            rep = await import_dre(session, SEED_ORG_ID, rows, dry_run=False)
            await session.flush()
            assert rep.inserted == 11
            # delete-by-mês + insert → exatamente 11 'trinks' nesses meses, seja qual
            # for o baseline (determinístico).
            assert await _count_trinks_months(session, SEED_ORG_ID, _MONTHS) == 11

            # Idempotência: re-rodar remove as 11 e reinsere 11 (não duplica).
            rep2 = await import_dre(session, SEED_ORG_ID, rows, dry_run=False)
            await session.flush()
            assert rep2.removed_existing == 11
            assert await _count_trinks_months(session, SEED_ORG_ID, _MONTHS) == 11

            # Confere uma linha-folha de despesa (subgrupo + valor).
            salarios = (
                await session.execute(
                    select(DreMonthlyLine).where(
                        DreMonthlyLine.organization_id == SEED_ORG_ID,
                        DreMonthlyLine.source == "trinks",
                        DreMonthlyLine.line_item == "Salários",
                        DreMonthlyLine.competence_month == date(2026, 3, 1),
                    )
                )
            ).scalars().all()
            assert any(
                s.subgroup == "pessoal" and s.amount == Decimal("500.00")
                for s in salarios
            )
        finally:
            await session.rollback()
