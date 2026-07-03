"""Testes dos parsers de débitos e ranking da Trinks (puros, sem DB)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.trinks_cash_closing import parse_cash_closings
from app.services.trinks_debts import parse_debts
from app.services.trinks_ranking import parse_ranking

FIXT = Path(__file__).parent / "fixtures" / "trinks"


def test_parse_debts():
    rows, rep = parse_debts(FIXT / "debitos_sample.csv")
    assert rep.total_rows == 2
    assert rep.parsed == 2
    assert rep.total_amount == 140.0
    assert rows[0].amount == Decimal("90.00")
    assert rows[0].kind == "agendamento_nao_pago"
    assert rows[1].kind == "fechamento_com_divida"
    assert rows[0].client_name == "João Silva"


def test_parse_ranking():
    rows, rep = parse_ranking(FIXT / "ranking_sample.csv")
    assert rep.total_rows == 2
    assert rep.parsed == 2
    assert rep.no_phone == 1          # Maria sem telefone
    assert rep.with_email == 2
    assert rep.with_birth == 2
    joao = rows[0]
    assert joao.phone == "+5563992287396"
    assert joao.email == "joao@x.com"  # normalizado p/ minúsculas
    assert joao.birth_date == date(1990, 3, 15)


def test_parse_cash_closings():
    rows, rep = parse_cash_closings(FIXT / "fechamento_caixa_sample.csv")
    assert rep.total_rows == 2
    assert rep.parsed == 2
    assert rep.no_date == 0
    first, second = rows
    assert first.closing_date == date(2026, 1, 5)
    assert first.opening_balance == Decimal("969.00")
    assert first.cash_received == Decimal("445.00")
    assert first.closing_balance == Decimal("1414.00")
    assert first.other_methods_received == Decimal("2068.00")
    assert second.closing_date == date(2026, 1, 6)
    assert second.withdrawal == Decimal("8.00")
    assert second.other_methods_expenses == Decimal("-7312.02")
    # rodapé "Total período" (1ª coluna vazia) não vira registro (só 2 linhas, não 3)
    assert len(rows) == 2
