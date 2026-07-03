"""Billing no painel de plataforma (migration 0033 + /platform/billing/*).

Cobre: isolamento (401), catálogo de planos (list/create/patch), visão de
assinaturas com dunning, ação administrativa via API (pause/resume), cupons
(create/validação/deactivate) e listagem de webhook-events.

Requer `ADMIN_DATABASE_URL` — mesmo padrão dos demais testes de plataforma.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.security import hash_password

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
PLATFORM_EMAIL = "test-superadmin-pbilling@plataforma-test.com"
PLATFORM_PASSWORD = "superadmin-test-123"


@pytest_asyncio.fixture
async def platform_headers(client):
    if not ADMIN_URL:
        pytest.skip("ADMIN_DATABASE_URL ausente — testes de plataforma exigem role dona.")
    eng = create_engine(ADMIN_URL)
    with Session(eng) as s, s.begin():
        s.execute(
            text(
                "INSERT INTO platform_admins (email, password_hash) VALUES (:e, :p) "
                "ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash"
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
        s.execute(
            text(
                "DELETE FROM billing_events WHERE actor_type='platform_admin' AND actor_id IN "
                "(SELECT id FROM platform_admins WHERE email=:e)"
            ),
            {"e": PLATFORM_EMAIL},
        )
        # As ações administrativas também geram auditoria (M9) — FK RESTRICT
        # exige limpar antes do admin.
        s.execute(
            text(
                "DELETE FROM platform_audit_log WHERE admin_id IN "
                "(SELECT id FROM platform_admins WHERE email=:e)"
            ),
            {"e": PLATFORM_EMAIL},
        )
        s.execute(text("DELETE FROM platform_admins WHERE email=:e"), {"e": PLATFORM_EMAIL})


def _purge_plan(name: str) -> None:
    eng = create_engine(ADMIN_URL)
    with Session(eng) as s, s.begin():
        s.execute(
            text(
                "DELETE FROM plan_prices WHERE plan_id IN (SELECT id FROM plans WHERE name=:n);"
            ),
            {"n": name},
        )
        s.execute(
            text("DELETE FROM plan_limits WHERE plan_id IN (SELECT id FROM plans WHERE name=:n)"),
            {"n": name},
        )
        s.execute(text("DELETE FROM plans WHERE name=:n"), {"n": name})


@pytest.mark.asyncio
async def test_billing_sem_token_401(client):
    for path in ("/platform/billing/plans", "/platform/billing/subscriptions"):
        r = await client.get(path)
        assert r.status_code in (401, 403), path


@pytest.mark.asyncio
async def test_planos_list_create_patch(client, platform_headers):
    r = await client.get("/platform/billing/plans", headers=platform_headers)
    assert r.status_code == 200, r.text
    base = r.json()
    assert len(base) >= 1
    assert {"id", "name", "prices", "limits", "is_active"} <= set(base[0])
    assert "barbers" in base[0]["limits"]

    try:
        rc = await client.post(
            "/platform/billing/plans",
            headers=platform_headers,
            json={
                "name": "Plano Teste M8",
                "price_month": 149.9,
                "price_year": 1499.0,
                "limits": {"units": 2, "barbers": 8},
                "sort_order": 99,
            },
        )
        assert rc.status_code == 201, rc.text
        plan = rc.json()
        assert plan["limits"]["barbers"] == 8
        cycles = {p["cycle"]: p["amount"] for p in plan["prices"]}
        assert cycles == {"monthly": 149.9, "yearly": 1499.0}

        rp = await client.patch(
            f"/platform/billing/plans/{plan['id']}",
            headers=platform_headers,
            json={"price_month": 159.9, "limits": {"barbers": 10}, "is_active": False},
        )
        assert rp.status_code == 200, rp.text
        updated = rp.json()
        assert updated["price_month"] == 159.9
        assert updated["limits"]["barbers"] == 10
        assert updated["is_active"] is False
    finally:
        _purge_plan("Plano Teste M8")


@pytest.mark.asyncio
async def test_assinaturas_dunning_e_acao(client, platform_headers):
    r = await client.get("/platform/billing/subscriptions", headers=platform_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 1
    row = rows[0]
    assert {"org_id", "org_name", "status", "open_invoices", "days_overdue"} <= set(row)

    # pause/resume via API numa org com assinatura (usa a primeira da lista).
    org_id = row["org_id"]
    original_status = row["status"]
    rp = await client.post(
        f"/platform/billing/orgs/{org_id}/pause", headers=platform_headers
    )
    assert rp.status_code == 200, rp.text
    rr = await client.post(
        f"/platform/billing/orgs/{org_id}/resume", headers=platform_headers
    )
    assert rr.status_code == 200, rr.text
    # resume deixa 'active'; restaura o status original p/ não poluir o staging.
    if original_status != "active" and ADMIN_URL:
        eng = create_engine(ADMIN_URL)
        with Session(eng) as s, s.begin():
            s.execute(
                text(
                    "UPDATE subscriptions SET status=:st WHERE id="
                    "(SELECT id FROM subscriptions WHERE organization_id=:o "
                    "ORDER BY created_at DESC, id DESC LIMIT 1)"
                ),
                {"st": original_status, "o": org_id},
            )


@pytest.mark.asyncio
async def test_cupons_e_webhook_events(client, platform_headers):
    rbad = await client.post(
        "/platform/billing/coupons", headers=platform_headers,
        json={"code": "SEMVALOR"},
    )
    assert rbad.status_code == 400

    rc = await client.post(
        "/platform/billing/coupons", headers=platform_headers,
        json={"code": "m8teste20", "percent_off": 20, "duration": "once"},
    )
    assert rc.status_code == 201, rc.text
    coupon = rc.json()
    assert coupon["code"] == "M8TESTE20"
    try:
        rl = await client.get("/platform/billing/coupons", headers=platform_headers)
        assert any(c["code"] == "M8TESTE20" for c in rl.json())
        rd = await client.post(
            f"/platform/billing/coupons/{coupon['id']}/deactivate", headers=platform_headers
        )
        assert rd.status_code == 200 and rd.json()["active"] is False
    finally:
        eng = create_engine(ADMIN_URL)
        with Session(eng) as s, s.begin():
            s.execute(text("DELETE FROM coupons WHERE code='M8TESTE20'"))

    rw = await client.get("/platform/billing/webhook-events", headers=platform_headers)
    assert rw.status_code == 200
    assert isinstance(rw.json(), list)
