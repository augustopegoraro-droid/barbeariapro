"""Billing do SaaS (migration 0032 + services/billing + /billing/*).

Fluxos cobertos (provider MOCK, org descartável criada via /platform/orgs):
- Checkout ativa a assinatura (claim da sub trial local, plano por price,
  fatura paga + pagamento + billing_events).
- Ações administrativas: pause/resume, cancel at_period_end/imediato,
  reactivate, dias grátis, cupom, crédito.
- Lifecycle manual: trial vencido → past_due → canceled (com carência),
  escopado por `only_org_ids` (não toca as demais orgs do staging).
- Entitlements: full (ativa) / blocked (cancelada); check_limit hard bloqueia.
- Tenant: GET /billing/subscription e /billing/plans (RBAC: barbeiro 403).

Requer `ADMIN_DATABASE_URL` — mesmo padrão de tests/test_platform.py.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, set_current_org
from app.services.billing import service as billing_svc

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
PLATFORM_EMAIL = "test-superadmin-billing@plataforma-test.com"
PLATFORM_PASSWORD = "superadmin-test-123"
OWNER_EMAIL = "owner-billing@plataforma-test.com"
OWNER_PASSWORD = "ownerbilling123"
ACTOR = {"type": "platform_admin", "id": None, "label": "teste"}


def _purge_billing_org(org_id: int) -> None:
    eng = create_engine(ADMIN_URL)
    stmts = [
        "DELETE FROM billing_events WHERE organization_id=:o",
        "DELETE FROM payment_attempts WHERE organization_id=:o",
        "DELETE FROM billing_payments WHERE organization_id=:o",
        "DELETE FROM invoices WHERE organization_id=:o",
        "DELETE FROM discounts WHERE organization_id=:o",
        "DELETE FROM billing_credits WHERE organization_id=:o",
        "DELETE FROM billing_customers WHERE organization_id=:o",
        "DELETE FROM usage_metrics WHERE organization_id=:o",
        "DELETE FROM platform_onboarding_overrides WHERE organization_id=:o",
        "DELETE FROM platform_org_notes WHERE organization_id=:o",
        "DELETE FROM user_units WHERE unit_id IN (SELECT id FROM units WHERE organization_id=:o)",
        "DELETE FROM business_hours WHERE unit_id IN (SELECT id FROM units WHERE organization_id=:o)",
        "DELETE FROM services WHERE organization_id=:o",
        "DELETE FROM users WHERE organization_id=:o",
        "DELETE FROM units WHERE organization_id=:o",
        "DELETE FROM subscriptions WHERE organization_id=:o",
        "DELETE FROM organizations WHERE id=:o",
    ]
    with Session(eng) as s, s.begin():
        for stmt in stmts:
            s.execute(text(stmt), {"o": org_id})


@pytest_asyncio.fixture
async def billing_org(client):
    """Org descartável com assinatura trial manual (mesmo fluxo do onboarding)."""
    if not ADMIN_URL:
        pytest.skip("ADMIN_DATABASE_URL ausente — testes de billing exigem role dona.")
    eng = create_engine(ADMIN_URL)
    with Session(eng) as s, s.begin():
        s.execute(
            text(
                "INSERT INTO platform_admins (email, password_hash) VALUES (:e, :p) "
                "ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash"
            ),
            {"e": PLATFORM_EMAIL, "p": hash_password(PLATFORM_PASSWORD)},
        )
        plan_id = s.execute(text("SELECT id FROM plans ORDER BY id LIMIT 1")).scalar_one_or_none()
    if plan_id is None:
        pytest.skip("Nenhum plano cadastrado.")
    login = await client.post(
        "/platform/auth/login", json={"email": PLATFORM_EMAIL, "password": PLATFORM_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/platform/orgs",
        headers=headers,
        json={
            "name": "Barbearia Billing Teste",
            "subdomain": "billing-teste-xyz",
            "plan_id": int(plan_id),
            "owner_email": OWNER_EMAIL,
            "owner_password": OWNER_PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["org_id"]
    yield {"org_id": org_id, "plan_id": int(plan_id), "platform_headers": headers}
    # Idem test_auth_sessions.py/test_platform.py: engine síncrona bloqueia a
    # thread — esvazia as Tasks de auditoria do owner novo antes do DELETE
    # síncrono para não deadlockar com uma escrita ainda em voo.
    from app.services.audit import wait_for_pending

    await wait_for_pending()
    _purge_billing_org(org_id)
    with Session(eng) as s, s.begin():
        s.execute(text("DELETE FROM platform_admins WHERE email=:e"), {"e": PLATFORM_EMAIL})


async def _sub_row(org_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            row = (
                await session.execute(
                    text(
                        "SELECT status::text AS status, provider, provider_subscription_id, "
                        "cancel_at_period_end, current_period_end, plan_id "
                        "FROM subscriptions WHERE organization_id=:o "
                        "ORDER BY created_at DESC, id DESC LIMIT 1"
                    ),
                    {"o": org_id},
                )
            ).first()
    return dict(row._mapping)


@pytest.mark.asyncio
async def test_checkout_mock_ativa_assinatura(client, billing_org):
    org_id = billing_org["org_id"]
    url = await billing_svc.start_checkout(
        org_id, billing_org["plan_id"], "monthly",
        success_url="https://app.test/ok", cancel_url="https://app.test/cancel",
    )
    assert url == "https://app.test/ok"

    sub = await _sub_row(org_id)
    assert sub["status"] == "active"
    assert sub["provider"] == "mock" and sub["provider_subscription_id"]
    assert sub["plan_id"] == billing_org["plan_id"]

    # Fatura paga + pagamento + eventos registrados.
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            inv = (
                await session.execute(
                    text("SELECT status, amount_due FROM invoices WHERE organization_id=:o"),
                    {"o": org_id},
                )
            ).first()
            pay = (
                await session.execute(
                    text("SELECT status FROM billing_payments WHERE organization_id=:o"),
                    {"o": org_id},
                )
            ).first()
            kinds = (
                await session.execute(
                    text("SELECT event_type FROM billing_events WHERE organization_id=:o"),
                    {"o": org_id},
                )
            ).scalars().all()
    assert inv is not None and inv.status == "paid"
    assert pay is not None and pay.status == "succeeded"
    assert "checkout_started" in kinds and "provider_subscription_updated" in kinds

    # Segunda tentativa de checkout com assinatura viva no gateway → 409.
    with pytest.raises(billing_svc.BillingServiceError):
        await billing_svc.start_checkout(
            org_id, billing_org["plan_id"], "monthly",
            success_url="https://x/ok", cancel_url="https://x/no",
        )


@pytest.mark.asyncio
async def test_acoes_administrativas(client, billing_org):
    org_id = billing_org["org_id"]
    await billing_svc.start_checkout(
        org_id, billing_org["plan_id"], "monthly",
        success_url="https://x/ok", cancel_url="https://x/no",
    )

    await billing_svc.pause_subscription(org_id, actor=ACTOR)
    assert (await _sub_row(org_id))["status"] == "paused"

    await billing_svc.resume_subscription(org_id, actor=ACTOR)
    assert (await _sub_row(org_id))["status"] == "active"

    before = (await _sub_row(org_id))["current_period_end"]
    await billing_svc.grant_free_days(org_id, 15, actor=ACTOR)
    after = (await _sub_row(org_id))["current_period_end"]
    assert (after - before) >= timedelta(days=14)

    await billing_svc.cancel_subscription(org_id, at_period_end=True, actor=ACTOR)
    sub = await _sub_row(org_id)
    assert sub["cancel_at_period_end"] is True and sub["status"] == "active"

    await billing_svc.reactivate_subscription(org_id, actor=ACTOR)
    assert (await _sub_row(org_id))["cancel_at_period_end"] is False

    await billing_svc.cancel_subscription(org_id, at_period_end=False, actor=ACTOR)
    assert (await _sub_row(org_id))["status"] == "canceled"

    await billing_svc.grant_credit(org_id, Decimal("50"), reason="cortesia", actor=ACTOR)
    eng = create_engine(ADMIN_URL)
    with Session(eng) as s:
        saldo = s.execute(
            text("SELECT COALESCE(sum(amount),0) FROM billing_credits WHERE organization_id=:o"),
            {"o": org_id},
        ).scalar_one()
        s.execute(
            text(
                "INSERT INTO coupons (code, percent_off, duration) "
                "VALUES ('TESTE10', 10, 'once') ON CONFLICT (code) DO NOTHING"
            )
        )
        s.commit()
    assert saldo == Decimal("50")
    try:
        await billing_svc.apply_coupon(org_id, "TESTE10", reason="retenção", actor=ACTOR)
        with Session(eng) as s:
            n = s.execute(
                text("SELECT count(*) FROM discounts WHERE organization_id=:o"), {"o": org_id}
            ).scalar_one()
        assert n == 1
    finally:
        with Session(eng) as s, s.begin():
            s.execute(text("DELETE FROM discounts WHERE organization_id=:o"), {"o": org_id})
            s.execute(text("DELETE FROM coupons WHERE code='TESTE10'"))


@pytest.mark.asyncio
async def test_lifecycle_manual(client, billing_org):
    org_id = billing_org["org_id"]
    now = datetime.now(timezone.utc)
    eng = create_engine(ADMIN_URL)

    # Trial vencido ontem → past_due (só esta org). Recua início e fim juntos
    # para respeitar o CHECK subs_period_valid (end > start).
    with Session(eng) as s, s.begin():
        s.execute(
            text(
                "UPDATE subscriptions SET current_period_start=:s, current_period_end=:e "
                "WHERE organization_id=:o"
            ),
            {"s": now - timedelta(days=31), "e": now - timedelta(days=1), "o": org_id},
        )
    moved = await billing_svc.run_lifecycle(now, only_org_ids=[org_id])
    assert moved["to_past_due"] == 1
    assert (await _sub_row(org_id))["status"] == "past_due"

    # Além da carência → canceled.
    grace = settings.billing_grace_days_past_due
    with Session(eng) as s, s.begin():
        s.execute(
            text("UPDATE subscriptions SET current_period_end=:e WHERE organization_id=:o"),
            {"e": now - timedelta(days=grace + 1), "o": org_id},
        )
    moved = await billing_svc.run_lifecycle(now, only_org_ids=[org_id])
    assert moved["to_canceled"] == 1
    assert (await _sub_row(org_id))["status"] == "canceled"


@pytest.mark.asyncio
async def test_entitlements_e_tenant_api(client, billing_org):
    from app.core.entitlements import check_limit, get_entitlements
    from fastapi import HTTPException

    org_id = billing_org["org_id"]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            ent = await get_entitlements(session)
            assert ent.level == "full" and ent.limits.get("barbers") is not None

            # hard: estourar o limite bloqueia com 402
            old = settings.billing_enforcement
            settings.billing_enforcement = "hard"
            try:
                with pytest.raises(HTTPException) as exc:
                    await check_limit(session, "barbers", current_count=10_000)
                assert exc.value.status_code == 402
            finally:
                settings.billing_enforcement = old

    # Tenant API: owner vê a assinatura; catálogo de planos responde.
    login = await client.post(
        "/auth/login",
        json={"organization_id": org_id, "email": OWNER_EMAIL, "password": OWNER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    rs = await client.get("/billing/subscription", headers=headers)
    assert rs.status_code == 200, rs.text
    body = rs.json()
    assert body["status"] == "trial" and body["level"] == "full"
    assert body["limits"] and "barbers" in body["limits"]
    rp = await client.get("/billing/plans", headers=headers)
    assert rp.status_code == 200 and len(rp.json()) >= 1


@pytest.mark.asyncio
async def test_webhook_stripe_assinatura_e_idempotencia(client, billing_org, monkeypatch):
    """Assinatura HMAC verificada + replay do mesmo event_id não reprocessa."""
    import hashlib
    import hmac
    import json
    import time

    monkeypatch.setattr(settings, "billing_provider", "stripe")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_teste")

    ts = int(time.time())
    payload = json.dumps(
        {
            "id": "evt_teste_001",
            "object": "event",
            "api_version": "2026-06-24.dahlia",
            "created": ts,
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_desconhecida",
                    "object": "subscription",
                    "status": "active",
                    "customer": "cus_inexistente",
                    "items": {"data": []},
                }
            },
        }
    ).encode()
    signed = hmac.new(b"whsec_teste", f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    good = {"stripe-signature": f"t={ts},v1={signed}"}

    # Assinatura inválida → 400 (gateway fará retry).
    r_bad = await client.post(
        "/billing/webhooks/stripe", content=payload,
        headers={"stripe-signature": f"t={ts},v1=deadbeef"},
    )
    assert r_bad.status_code == 400

    # Assinatura válida, customer não mapeado → registrado como failed (200).
    r1 = await client.post("/billing/webhooks/stripe", content=payload, headers=good)
    assert r1.status_code == 200, r1.text
    assert r1.json()["received"] == 1 and r1.json()["failed"] == 1

    # Replay do MESMO event id → deduplicado, nada reprocessa.
    r2 = await client.post("/billing/webhooks/stripe", content=payload, headers=good)
    assert r2.status_code == 200
    assert r2.json()["duplicated"] == 1 and r2.json()["failed"] == 0

    eng = create_engine(ADMIN_URL)
    with Session(eng) as s, s.begin():
        s.execute(text("DELETE FROM webhook_events WHERE event_id='evt_teste_001'"))
