"""Métricas executivas da plataforma (migration 0028 + GET /platform/metrics).

Cobre:
- Sem token / token de tenant → 401 (mesmo isolamento do restante de /platform/*).
- Happy path: shape completo, série com o nº de meses pedido, invariantes
  (mrr ≥ 0, arr = mrr × 12, contagens coerentes com /platform/orgs).
- Validação do parâmetro `months` (0 e 37 → 422).

Requer `ADMIN_DATABASE_URL` (role dona) para semear o superadmin — mesmo padrão
de tests/test_platform.py (pytest.skip se ausente).
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.security import hash_password

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
PLATFORM_EMAIL = "test-superadmin-metrics@plataforma-test.com"
PLATFORM_PASSWORD = "superadmin-test-123"


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
async def test_metrics_sem_token_401(client):
    r = await client.get("/platform/metrics")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_metrics_token_de_tenant_rejeitado(client, auth_headers):
    r = await client.get("/platform/metrics", headers=auth_headers)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_metrics_shape_e_invariantes(client, platform_headers):
    r = await client.get("/platform/metrics?months=6", headers=platform_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert {"mrr", "arr", "arpu", "churn_rate", "ltv", "counts", "series"} <= set(body)
    assert body["mrr"] >= 0
    assert body["arr"] == pytest.approx(body["mrr"] * 12, abs=0.02)

    # Série: exatamente os meses pedidos, ordenada, campos completos e não-negativos.
    series = body["series"]
    assert len(series) == 6
    assert [p["month"] for p in series] == sorted(p["month"] for p in series)
    for p in series:
        assert {"month", "new_orgs", "canceled_subs", "active_subs", "trial_subs", "mrr"} <= set(p)
        assert p["new_orgs"] >= 0 and p["canceled_subs"] >= 0
        assert p["active_subs"] >= 0 and p["trial_subs"] >= 0 and p["mrr"] >= 0

    # Coerência com a listagem: contagens por status somam o total de orgs.
    rl = await client.get("/platform/orgs", headers=platform_headers)
    assert rl.status_code == 200
    assert sum(body["counts"].values()) == len(rl.json())


@pytest.mark.asyncio
async def test_metrics_valida_parametro_months(client, platform_headers):
    for bad in (0, 37):
        r = await client.get(f"/platform/metrics?months={bad}", headers=platform_headers)
        assert r.status_code == 422, f"months={bad} → {r.status_code}"
