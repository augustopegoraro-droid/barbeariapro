"""Testes do import de TRANSAÇÕES DE PAGAMENTO (Pagamentos/Estornos) da Trinks.

Duas camadas:
- Puros (sem DB): parsers de moeda BR (com sinal), data, extração das colunas e
  descarte de linha sem data.
- Integração (sessão RLS direta, `rollback()` no fim): dry-run não grava; commit
  substitui o período (delete-by-range + insert) e é idempotente.

Os de integração usam a fixture `auth_headers` só como *gate*: se o DB semeado
estiver indisponível, o login falha e o teste é pulado. Nada é comitado (sempre
`rollback`), então não há efeito colateral.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, set_current_org
from app.services.trinks_payments import (
    _parse_amount,
    _parse_amount_opt,
    _parse_date,
    import_payments,
    parse_payments,
)
from models import PaymentTransaction

FIXT = Path(__file__).parent / "fixtures" / "trinks"
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))

# Intervalo coberto pela fixture (05/01 → 10/02/2026).
_RANGE = (date(2026, 1, 5), date(2026, 2, 10))


# ─────────────────────────── parsers puros (sem DB) ───────────────────────────


def test_parse_payments_extrai_colunas():
    rows, rep = parse_payments(FIXT / "payments_sample.csv")
    assert rep.total_rows == 3
    assert rep.parsed == 3
    assert rep.skipped_no_date == 0

    dinheiro, credito, pix = rows

    assert dinheiro.payment_type == "À Vista"
    assert dinheiro.payment_method == "Dinheiro"
    assert dinheiro.movement_date == date(2026, 1, 5)
    assert dinheiro.amount_paid == Decimal("50.00")
    assert dinheiro.operator_discount_amount == Decimal("0.00")
    assert dinheiro.amount_to_receive == Decimal("50.00")
    assert dinheiro.account is None  # célula vazia → None
    assert dinheiro.comanda is None
    assert dinheiro.anticipated is False
    assert dinheiro.entry_type == "Pagamento"

    assert credito.payment_type == "Crédito"
    assert credito.payment_method == "Mastercard"
    assert credito.operator_discount_pct == Decimal("2.99")
    assert credito.operator_discount_amount == Decimal("-5.38")  # taxa negativa
    assert credito.amount_paid == Decimal("180.00")
    assert credito.amount_to_receive == Decimal("174.62")
    assert credito.service_date == date(2026, 1, 5)
    assert credito.expected_receipt_date == date(2026, 1, 7)
    assert credito.comanda == "C-1002"
    assert credito.account == "BANCO ITAU"

    assert pix.movement_date == date(2026, 2, 10)
    assert pix.payment_method == "PIX"
    assert pix.account == "BANCO CORA"


def test_parse_amount_preserva_sinal():
    assert _parse_amount("50,00") == Decimal("50.00")
    assert _parse_amount("7.371,00") == Decimal("7371.00")
    assert _parse_amount("1.234.567,89") == Decimal("1234567.89")
    assert _parse_amount("-5,38") == Decimal("-5.38")  # desconto de operadora
    assert _parse_amount("R$ 1.000,00") == Decimal("1000.00")
    assert _parse_amount("") == Decimal("0.00")
    assert _parse_amount("   ") == Decimal("0.00")
    assert _parse_amount("abc") == Decimal("0.00")  # inválido → 0, sem estourar


def test_parse_amount_opt_distingue_vazio():
    assert _parse_amount_opt("") is None
    assert _parse_amount_opt("   ") is None
    assert _parse_amount_opt("0,00") == Decimal("0.00")
    assert _parse_amount_opt("2,99") == Decimal("2.99")


def test_parse_date():
    assert _parse_date("05/01/2026") == date(2026, 1, 5)
    assert _parse_date("05/01/2026 14:30") == date(2026, 1, 5)  # ignora a hora anexa
    assert _parse_date("2026-01-05") == date(2026, 1, 5)
    assert _parse_date("") is None
    assert _parse_date("sem data") is None


def test_parse_pula_linha_sem_data():
    # Cabeçalho reduzido (o parser mapeia por nome; colunas ausentes viram vazio).
    csv_bytes = (
        "Tipo de Forma de Pagamento;Forma de Pagamento;Data Atendimento/Venda;"
        "Data Movimentação;Valor Pago;Valor a ser Recebido\n"
        "À Vista;Dinheiro;;;50,00;50,00\n"  # sem data alguma → descartada
        "À Vista;Dinheiro;05/01/2026;05/01/2026;50,00;50,00\n"
    ).encode("utf-8")
    rows, rep = parse_payments(csv_bytes)
    assert rep.total_rows == 2
    assert rep.parsed == 1
    assert rep.skipped_no_date == 1
    assert rows[0].movement_date == date(2026, 1, 5)


def test_parse_usa_atendimento_quando_falta_movimentacao():
    csv_bytes = (
        "Tipo de Forma de Pagamento;Forma de Pagamento;Data Atendimento/Venda;"
        "Data Movimentação;Valor Pago;Valor a ser Recebido\n"
        "À Vista;Dinheiro;08/01/2026;;50,00;50,00\n"  # só data de atendimento
    ).encode("utf-8")
    rows, rep = parse_payments(csv_bytes)
    assert rep.parsed == 1
    assert rows[0].movement_date == date(2026, 1, 8)  # cai para a data do atendimento


# ─────────────────── integração (sessão RLS direta, sempre rollback) ───────────────────


async def _count_trinks_in_range(session, org, start, end) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(PaymentTransaction)
            .where(
                PaymentTransaction.organization_id == org,
                PaymentTransaction.source == "trinks",
                PaymentTransaction.movement_date >= start,
                PaymentTransaction.movement_date <= end,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_import_dry_run_nao_grava(auth_headers):
    rows, _ = parse_payments(FIXT / "payments_sample.csv")
    start, end = _RANGE
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        try:
            before = await _count_trinks_in_range(session, SEED_ORG_ID, start, end)
            rep = await import_payments(session, SEED_ORG_ID, rows, dry_run=True)
            assert rep.inserted == 3
            assert rep.range_start == start
            assert rep.range_end == end
            assert rep.sum_amount_paid == Decimal("320.00")
            assert rep.sum_amount_to_receive == Decimal("314.62")
            assert rep.sum_operator_discount == Decimal("-5.38")
            after = await _count_trinks_in_range(session, SEED_ORG_ID, start, end)
            assert after == before  # dry-run não gravou nada
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_import_commit_substitui_periodo_idempotente(auth_headers):
    rows, _ = parse_payments(FIXT / "payments_sample.csv")
    start, end = _RANGE
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        try:
            rep = await import_payments(session, SEED_ORG_ID, rows, dry_run=False)
            await session.flush()
            assert rep.inserted == 3
            # delete-by-range + insert → exatamente 3 'trinks' no período, seja qual
            # for o baseline (determinístico).
            assert await _count_trinks_in_range(session, SEED_ORG_ID, start, end) == 3

            # Idempotência: re-rodar remove as 3 e reinsere 3 (não duplica).
            rep2 = await import_payments(session, SEED_ORG_ID, rows, dry_run=False)
            await session.flush()
            assert rep2.removed_existing == 3
            assert await _count_trinks_in_range(session, SEED_ORG_ID, start, end) == 3

            # Confere a linha do crédito (valor, taxa, líquido, conta).
            credito = (
                await session.execute(
                    select(PaymentTransaction).where(
                        PaymentTransaction.organization_id == SEED_ORG_ID,
                        PaymentTransaction.source == "trinks",
                        PaymentTransaction.payment_method == "Mastercard",
                        PaymentTransaction.movement_date == date(2026, 1, 5),
                    )
                )
            ).scalars().all()
            assert any(
                c.amount_paid == Decimal("180.00")
                and c.operator_discount_amount == Decimal("-5.38")
                and c.amount_to_receive == Decimal("174.62")
                and c.expected_receipt_date == date(2026, 1, 7)
                and c.account == "BANCO ITAU"
                for c in credito
            )
        finally:
            await session.rollback()
