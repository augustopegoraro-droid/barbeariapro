"""Regras configuráveis da Central de Operações (migration 0040 + M11).

Cobre:
- Isolamento: sem token / token de tenant → 401/403 (GET e PUT).
- GET: 6 regras semeadas com defaults do comportamento original (SA-D10).
- PUT: atualiza enabled/threshold/severity, grava updated_by e auditoria;
  kind desconhecido → 404; threshold fora da faixa → 422; health > 100 → 422.
- GET /platform/alerts respeita as regras: regra desligada → kind ausente.
- Cleanup: cada teste que muda regra restaura o default no fim.

Requer `ADMIN_DATABASE_URL` (role dona) — mesmo padrão de tests/test_platform.py.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.security import hash_password

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
PLATFORM_EMAIL = "test-superadmin-alert-rules@plataforma-test.com"
PLATFORM_PASSWORD = "superadmin-test-123"

# Defaults semeados na migration 0040 (comportamento original hardcoded).
SEED_DEFAULTS = {
    "payment_overdue": (True, 1, "critical"),
    "trial_ending": (True, 7, "warning"),
    "onboarding_stuck": (True, 7, "warning"),
    "inactive_account": (True, 30, "warning"),
    "webhook_failures": (True, 1, "critical"),
    "health_at_risk": (True, 40, "warning"),
}


@pytest_asyncio.fixture
async def platform_headers(client):
    """Semeia um superadmin (role dona) e devolve o header Bearer de plataforma."""
    if not ADMIN_URL:
        pytest.skip("ADMIN_DATABASE_URL ausente — testes de plataforma exigem role dona.")
    eng = create_engine(ADMIN_URL)
    with Session(eng) as s, s.begin():
        s.execute(
            text(
                """
                INSERT INTO platform_admins (email, password_hash)
                VALUES (:e, :p)
                ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash
                """
            ),
            {"e": PLATFORM_EMAIL, "p": hash_password(PLATFORM_PASSWORD)},
        )
    resp = await client.post(
        "/platform/auth/login",
        json={"email": PLATFORM_EMAIL, "password": PLATFORM_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    yield {"Authorization": f"Bearer {resp.json()['access_token']}"}
    with Session(eng) as s, s.begin():
        # Restaura defaults de TODAS as regras antes de remover o admin
        # (updated_by referencia só por snapshot de e-mail, sem FK).
        for kind, (enabled, threshold, severity) in SEED_DEFAULTS.items():
            s.execute(
                text(
                    """
                    UPDATE platform_alert_rules
                    SET enabled=:e, threshold=:t, severity=:s
                    WHERE kind=:k
                    """
                ),
                {"k": kind, "e": enabled, "t": threshold, "s": severity},
            )
        # Auditoria referencia o admin (FK RESTRICT) — limpar antes.
        s.execute(
            text(
                "DELETE FROM platform_audit_log WHERE admin_id IN "
                "(SELECT id FROM platform_admins WHERE email=:e)"
            ),
            {"e": PLATFORM_EMAIL},
        )
        s.execute(text("DELETE FROM platform_admins WHERE email=:e"), {"e": PLATFORM_EMAIL})


@pytest.mark.asyncio
async def test_alert_rules_sem_token_401(client):
    r = await client.get("/platform/alert-rules")
    assert r.status_code in (401, 403)
    r = await client.put(
        "/platform/alert-rules/trial_ending",
        json={"enabled": True, "threshold": 5, "severity": "warning"},
    )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_alert_rules_token_de_tenant_rejeitado(client, auth_headers):
    r = await client.get("/platform/alert-rules", headers=auth_headers)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_alert_rules_lista_defaults(client, platform_headers):
    r = await client.get("/platform/alert-rules", headers=platform_headers)
    assert r.status_code == 200, r.text
    rules = {x["kind"]: x for x in r.json()}
    assert set(rules) == set(SEED_DEFAULTS)
    for kind, (enabled, threshold, severity) in SEED_DEFAULTS.items():
        assert rules[kind]["enabled"] == enabled, kind
        assert rules[kind]["threshold"] == threshold, kind
        assert rules[kind]["severity"] == severity, kind
        # Metadados de exibição sempre presentes.
        assert rules[kind]["label"] and rules[kind]["unit"]


@pytest.mark.asyncio
async def test_alert_rule_put_atualiza_e_audita(client, platform_headers):
    r = await client.put(
        "/platform/alert-rules/trial_ending",
        json={"enabled": False, "threshold": 3, "severity": "info"},
        headers=platform_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["threshold"] == 3
    assert body["severity"] == "info"
    assert body["updated_by"] == PLATFORM_EMAIL

    # Persistiu (GET reflete) e auditou.
    r = await client.get("/platform/alert-rules", headers=platform_headers)
    rules = {x["kind"]: x for x in r.json()}
    assert rules["trial_ending"]["threshold"] == 3

    r = await client.get(
        "/platform/audit-log?limit=10", headers=platform_headers
    )
    assert r.status_code == 200
    actions = [row["action"] for row in r.json()]
    assert "alert_rule_updated" in actions


@pytest.mark.asyncio
async def test_alert_rule_put_validacoes(client, platform_headers):
    r = await client.put(
        "/platform/alert-rules/nao_existe",
        json={"enabled": True, "threshold": 1, "severity": "warning"},
        headers=platform_headers,
    )
    assert r.status_code == 404

    r = await client.put(
        "/platform/alert-rules/trial_ending",
        json={"enabled": True, "threshold": 5000, "severity": "warning"},
        headers=platform_headers,
    )
    assert r.status_code == 422

    r = await client.put(
        "/platform/alert-rules/health_at_risk",
        json={"enabled": True, "threshold": 200, "severity": "warning"},
        headers=platform_headers,
    )
    assert r.status_code == 422

    r = await client.put(
        "/platform/alert-rules/trial_ending",
        json={"enabled": True, "threshold": 5, "severity": "explosivo"},
        headers=platform_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_alerts_respeita_regra_desligada(client, platform_headers):
    # Desliga TODAS as regras → nenhum alerta, de nenhum kind.
    for kind, (_, threshold, severity) in SEED_DEFAULTS.items():
        threshold = min(threshold, 100)  # health_at_risk valida ≤100
        r = await client.put(
            f"/platform/alert-rules/{kind}",
            json={"enabled": False, "threshold": threshold, "severity": severity},
            headers=platform_headers,
        )
        assert r.status_code == 200, r.text

    r = await client.get("/platform/alerts", headers=platform_headers)
    assert r.status_code == 200, r.text
    assert r.json()["alerts"] == []
    assert r.json()["counts"] == {}


@pytest.mark.asyncio
async def test_alerts_health_at_risk_com_limiar_maximo(client, platform_headers):
    """Com limiar 100, toda org não-suspensa com score <100 alerta — prova que
    a regra nova dispara e carrega severidade da regra."""
    r = await client.put(
        "/platform/alert-rules/health_at_risk",
        json={"enabled": True, "threshold": 100, "severity": "info"},
        headers=platform_headers,
    )
    assert r.status_code == 200

    alerts = (
        await client.get("/platform/alerts", headers=platform_headers)
    ).json()["alerts"]
    health_alerts = [a for a in alerts if a["kind"] == "health_at_risk"]
    for a in health_alerts:
        assert a["severity"] == "info"
        assert a["org_id"] is not None
        assert a["href"] == f"/tenants/{a['org_id']}"

    # Coerência com /platform/health: mesmo universo de orgs abaixo do limiar.
    health = (
        await client.get("/platform/health", headers=platform_headers)
    ).json()
    below = [i for i in health["items"] if i["score"] < 100]
    assert len(health_alerts) == len(below)
