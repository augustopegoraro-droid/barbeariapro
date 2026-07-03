"""Derivação de etapas de onboarding (app/services/onboarding_progress.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import onboarding_progress as onb


def _signals(**kw) -> dict:
    base = dict(
        org_id=1,
        name="Org Teste",
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
        has_profile=False,
        wa_configured=False,
        barbers_count=0,
        services_count=0,
        clients_count=0,
        appointments_count=0,
        appt_30d=0,
        payments_count=0,
        expenses_count=0,
        has_revenue_goal=False,
        last_activity=None,
        sub_status="trial",
        sub_period_end=datetime.now(timezone.utc) + timedelta(days=10),
    )
    base.update(kw)
    return base


def test_org_recem_criada_so_conta_criada():
    items = onb.compute_checklist(_signals(), {})
    by_key = {i["key"]: i for i in items}
    assert by_key["conta_criada"]["done"] is True
    assert by_key["primeiro_acesso"]["done"] is False
    assert by_key["primeiro_acesso"]["derivable"] is False  # sem evento de login
    assert sum(1 for i in items if i["done"]) == 1
    assert onb.current_stage(items)["key"] == "primeiro_acesso"


def test_derivacao_completa():
    s = _signals(
        has_profile=True,
        wa_configured=True,
        barbers_count=3,
        services_count=15,
        clients_count=200,
        appointments_count=50,
        appt_30d=40,
        payments_count=30,
        expenses_count=5,
    )
    items = onb.compute_checklist(s, {"primeiro_acesso": True})
    assert all(i["done"] for i in items)
    assert onb.current_stage(items) is None


def test_limiarem_clientes_e_atividade():
    s = _signals(clients_count=onb.CLIENTS_IMPORT_THRESHOLD - 1, appt_30d=onb.ACTIVE_APPT_30D_THRESHOLD - 1)
    by_key = {i["key"]: i for i in onb.compute_checklist(s, {})}
    assert by_key["importacao_clientes"]["done"] is False
    assert by_key["cliente_ativo"]["done"] is False

    s2 = _signals(clients_count=onb.CLIENTS_IMPORT_THRESHOLD, appt_30d=onb.ACTIVE_APPT_30D_THRESHOLD)
    by_key2 = {i["key"]: i for i in onb.compute_checklist(s2, {})}
    assert by_key2["importacao_clientes"]["done"] is True
    assert by_key2["cliente_ativo"]["done"] is True


def test_override_vence_derivacao_nos_dois_sentidos():
    s = _signals(barbers_count=5)  # derivado: profissionais done
    by_key = {i["key"]: i for i in onb.compute_checklist(s, {"profissionais": False})}
    assert by_key["profissionais"]["done"] is False
    assert by_key["profissionais"]["source"] == "manual"

    by_key2 = {i["key"]: i for i in onb.compute_checklist(_signals(), {"whatsapp": True})}
    assert by_key2["whatsapp"]["done"] is True
    assert by_key2["whatsapp"]["source"] == "manual"


def test_financeiro_por_qualquer_sinal():
    for kw in (dict(expenses_count=1), dict(has_revenue_goal=True), dict(payments_count=1)):
        by_key = {i["key"]: i for i in onb.compute_checklist(_signals(**kw), {})}
        assert by_key["financeiro"]["done"] is True, kw


def test_stuck_days_e_trial_days_left():
    now = datetime.now(timezone.utc)
    s = _signals(last_activity=now - timedelta(days=12, hours=1))
    assert onb.stuck_days(s, now=now) == 12

    sem_atividade = _signals(created_at=now - timedelta(days=8, hours=2), last_activity=None)
    assert onb.stuck_days(sem_atividade, now=now) == 8

    assert onb.trial_days_left(_signals(sub_period_end=now + timedelta(days=9, hours=5)), now=now) == 9
    assert onb.trial_days_left(_signals(sub_status="active"), now=now) is None
