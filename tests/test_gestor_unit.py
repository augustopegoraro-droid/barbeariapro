"""Testes unitários das tools de gestão (D-52) — lógica pura, sem DB."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.core.dates import today_local
from app.services.management import _free_windows, is_manager_role, resolve_period


# ─── is_manager_role ──────────────────────────────────────────────────────────

def test_is_manager_role_autoriza_owner_e_manager():
    assert is_manager_role("owner") is True
    assert is_manager_role("manager") is True


def test_is_manager_role_nega_reception_barber_e_none():
    assert is_manager_role("reception") is False
    assert is_manager_role("barber") is False
    assert is_manager_role(None) is False


# ─── resolve_period ───────────────────────────────────────────────────────────

def test_resolve_period_hoje_e_default():
    today = today_local()
    assert resolve_period("hoje") == (today, today, "hoje")
    assert resolve_period(None) == (today, today, "hoje")
    assert resolve_period("xpto") == (today, today, "hoje")  # fallback


def test_resolve_period_ontem():
    y = today_local() - timedelta(days=1)
    assert resolve_period("ontem") == (y, y, "ontem")


def test_resolve_period_semana_comeca_na_segunda():
    today = today_local()
    df, dt, label = resolve_period("semana")
    assert dt == today
    assert df == today - timedelta(days=today.weekday())
    assert df.weekday() == 0  # segunda-feira
    assert label == "semana"


def test_resolve_period_mes_comeca_no_dia_1():
    today = today_local()
    df, dt, label = resolve_period("mes")
    assert df == today.replace(day=1)
    assert dt == today
    assert label == "mês"


def test_resolve_period_intervalo_explicito_tem_precedencia():
    a, b = date(2026, 1, 10), date(2026, 1, 20)
    assert resolve_period("mes", a, b) == (a, b, "2026-01-10..2026-01-20")


def test_resolve_period_intervalo_invertido_e_corrigido():
    a, b = date(2026, 1, 20), date(2026, 1, 10)
    df, dt, _ = resolve_period(None, a, b)
    assert (df, dt) == (date(2026, 1, 10), date(2026, 1, 20))


# ─── _free_windows (buracos na agenda) ────────────────────────────────────────

def _dt(h, m=0):
    return datetime(2026, 1, 5, h, m)


def test_free_windows_sem_ocupacao_devolve_janela_inteira():
    start, end = _dt(9), _dt(18)
    assert _free_windows([], start, end) == [(start, end)]


def test_free_windows_ocupado_no_meio_gera_dois_vaos():
    start, end = _dt(9), _dt(18)
    free = _free_windows([(_dt(12), _dt(13))], start, end)
    assert free == [(_dt(9), _dt(12)), (_dt(13), _dt(18))]


def test_free_windows_ocupacao_total_nao_deixa_vao():
    start, end = _dt(9), _dt(18)
    assert _free_windows([(_dt(8), _dt(19))], start, end) == []


def test_free_windows_intervalos_sobrepostos_sao_mesclados():
    start, end = _dt(9), _dt(18)
    free = _free_windows([(_dt(10), _dt(12)), (_dt(11), _dt(13))], start, end)
    assert free == [(_dt(9), _dt(10)), (_dt(13), _dt(18))]


# ─── builders do push (Fase C) ────────────────────────────────────────────────

from app.services.gestor_notify import build_alert_text, build_digest_text


def _digest():
    return {
        "date": "2026-06-28",
        "revenue": 1234.0,
        "appointment_count": 12,
        "top_barber": {"name": "Thedy", "revenue": 800.0},
        "noshows": 2,
        "ai_appointments": 3,
        "ai_revenue": 210.0,
        "tomorrow_idle_min": 90,
    }


def test_build_digest_text_contem_numeros_chave():
    txt = build_digest_text(_digest())
    assert "Resumo do dia" in txt and "2026-06-28" in txt
    assert "Thedy" in txt
    assert "12 atend" in txt
    assert "1h30" in txt  # 90 min de ociosidade


def test_build_digest_text_omite_secoes_zeradas():
    d = _digest()
    d.update(noshows=0, ai_appointments=0, tomorrow_idle_min=0, top_barber=None)
    txt = build_digest_text(d)
    assert "Faltas" not in txt and "Pela IA" not in txt and "Ociosidade" not in txt


def test_build_alert_text_junta_mensagens():
    alerts = [{"type": "meta", "message": "abaixo da meta"},
              {"type": "queda", "message": "movimento caiu"}]
    txt = build_alert_text(alerts)
    assert "Alerta de gestão" in txt
    assert "abaixo da meta" in txt and "movimento caiu" in txt
