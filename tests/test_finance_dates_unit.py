"""
Testes unitários dos helpers de intervalo de datas do financeiro/dashboard.

Um erro de fronteira aqui produz relatórios financeiros com período errado
(ex.: último dia do mês, virada de ano, ano bissexto).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, timedelta

import pytest
from fastapi import HTTPException


# ────────────────────────────────────────────────────────────
# financeiro._month_range — 'YYYY-MM' → (1º dia, último dia)
# ────────────────────────────────────────────────────────────

def test_month_range_mes_comum():
    from app.api.financeiro import _month_range
    assert _month_range("2026-06") == (date(2026, 6, 1), date(2026, 6, 30))


def test_month_range_dezembro_vira_ano():
    from app.api.financeiro import _month_range
    assert _month_range("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))


def test_month_range_fevereiro_bissexto():
    from app.api.financeiro import _month_range
    assert _month_range("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))


def test_month_range_fevereiro_nao_bissexto():
    from app.api.financeiro import _month_range
    assert _month_range("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026-99", "2026-6", "junho", "2026/06", ""])
def test_month_range_rejeita_formato_invalido(bad):
    from app.api.financeiro import _month_range
    with pytest.raises(HTTPException) as exc:
        _month_range(bad)
    assert exc.value.status_code == 422


# ────────────────────────────────────────────────────────────
# dashboard._period_range — relativo a hoje (fuso local)
# ────────────────────────────────────────────────────────────

def test_period_range_hoje():
    from app.api.dashboard import _period_range
    from app.core.dates import today_local
    today = today_local()
    assert _period_range("hoje") == (today, today)


def test_period_range_7d_inclui_hoje():
    from app.api.dashboard import _period_range
    from app.core.dates import today_local
    today = today_local()
    start, end = _period_range("7d")
    assert end == today
    assert start == today - timedelta(days=6)  # janela de 7 dias inclusiva


def test_period_range_30d():
    from app.api.dashboard import _period_range
    from app.core.dates import today_local
    today = today_local()
    start, end = _period_range("30d")
    assert (start, end) == (today - timedelta(days=29), today)


def test_period_range_mes_comeca_no_dia_1():
    from app.api.dashboard import _period_range
    from app.core.dates import today_local
    today = today_local()
    start, end = _period_range("mes")
    assert start == today.replace(day=1)
    assert end == today
