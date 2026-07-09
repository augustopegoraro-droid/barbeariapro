"""Health score por tenant (app/services/health.py + GET /platform/health).

Cobre:
- Unidade (função pura, sem DB): faixas, penalidade de inadimplência,
  carência de conta nova, suspensa → 0.
- Endpoint: isolamento (sem token / token de tenant → 401/403), shape,
  ordenação piores-primeiro, invariantes (score 0–100, mrr_at_risk ≥ 0).
- /orgs/overview passa a expor health_score/band/reasons e aceita order=health.

Requer `ADMIN_DATABASE_URL` (role dona) para semear o superadmin — mesmo padrão
de tests/test_platform.py (pytest.skip se ausente).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.services.health import (
    BAND_AT_RISK,
    BAND_HEALTHY,
    BAND_SUSPENDED,
    BAND_WATCH,
    compute_health,
)

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
PLATFORM_EMAIL = "test-superadmin-health@plataforma-test.com"
PLATFORM_PASSWORD = "superadmin-test-123"

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _row(**overrides) -> dict:
    """Org saudável de referência; testes sobrescrevem só o que interessa."""
    base = {
        "status": "active",
        "deleted_at": None,
        "created_at": NOW - timedelta(days=200),
        "last_activity": NOW - timedelta(days=1),
        "appt_30d": 40,
        "users_count": 3,
        "barbers_count": 2,
        "clients_count": 80,
        "days_overdue": 0,
        "open_amount": 0,
    }
    base.update(overrides)
    return base


# ─── unidade (função pura) ─────────────────────────────────────────────────────

def test_org_saudavel_fica_healthy():
    h = compute_health(_row(), now=NOW)
    assert h["band"] == BAND_HEALTHY
    assert h["score"] == 100
    assert h["reasons"] == []


def test_score_sempre_entre_0_e_100():
    for row in (
        _row(),
        _row(status="canceled", appt_30d=0, last_activity=None,
             barbers_count=0, clients_count=0, users_count=0),
        _row(days_overdue=999, open_amount=5000),
    ):
        h = compute_health(row, now=NOW)
        assert 0 <= h["score"] <= 100


def test_inadimplencia_penaliza_e_explica():
    h = compute_health(
        _row(status="past_due", days_overdue=10, open_amount=99.9), now=NOW
    )
    assert h["score"] < compute_health(_row(), now=NOW)["score"]
    assert any("atraso há 10 dia" in r for r in h["reasons"])


def test_inativa_e_cancelada_cai_para_at_risk():
    h = compute_health(
        _row(status="canceled", last_activity=NOW - timedelta(days=45),
             appt_30d=0, clients_count=0, barbers_count=0, users_count=0),
        now=NOW,
    )
    assert h["band"] == BAND_AT_RISK
    assert any("cancelada" in r for r in h["reasons"])
    assert any("sem atividade há 45 dias" in r for r in h["reasons"])


def test_conta_nova_tem_carencia_nunca_at_risk():
    h = compute_health(
        _row(status="trial", created_at=NOW - timedelta(days=2),
             last_activity=None, appt_30d=0, clients_count=0,
             barbers_count=0, users_count=1),
        now=NOW,
    )
    assert h["band"] == BAND_WATCH
    assert any("carência" in r for r in h["reasons"])


def test_suspensa_score_zero():
    h = compute_health(_row(deleted_at=NOW), now=NOW)
    assert h == {"score": 0, "band": BAND_SUSPENDED, "reasons": ["conta suspensa"]}


# ─── endpoint ──────────────────────────────────────────────────────────────────

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
        s.execute(text("DELETE FROM platform_admins WHERE email=:e"), {"e": PLATFORM_EMAIL})


@pytest.mark.asyncio
async def test_health_sem_token_401(client):
    r = await client.get("/platform/health")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_health_token_de_tenant_rejeitado(client, auth_headers):
    r = await client.get("/platform/health", headers=auth_headers)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_health_shape_e_invariantes(client, platform_headers):
    r = await client.get("/platform/health", headers=platform_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert {"counts", "mrr_at_risk", "items"} <= set(body)
    assert body["mrr_at_risk"] >= 0
    assert BAND_SUSPENDED not in body["counts"]

    scores = [i["score"] for i in body["items"]]
    assert scores == sorted(scores)  # piores primeiro
    for item in body["items"]:
        assert {"org_id", "name", "status", "score", "band", "reasons"} <= set(item)
        assert 0 <= item["score"] <= 100
        assert item["band"] in (BAND_HEALTHY, BAND_WATCH, BAND_AT_RISK)


@pytest.mark.asyncio
async def test_overview_expoe_health_e_ordena(client, platform_headers):
    r = await client.get(
        "/platform/orgs/overview?order=health", headers=platform_headers
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    for it in items:
        assert {"health_score", "health_band", "health_reasons"} <= set(it)
        assert 0 <= it["health_score"] <= 100
    scores = [i["health_score"] for i in items]
    assert scores == sorted(scores)
