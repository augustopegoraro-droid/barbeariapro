"""Visibilidade do site público (Fase 6): permissão, lazy-create, update e auditoria."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_get_requires_permission(client, barber_headers):
    resp = await client.get("/admin/security/site-visibility", headers=barber_headers)
    assert resp.status_code == 403


async def test_get_lazy_creates_defaults(client, auth_headers):
    resp = await client.get("/admin/security/site-visibility", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["services"]["mode"] == "all"
    assert body["professionals"]["mode"] == "all"
    assert body["show_hours"] is True
    assert body["banner"]["enabled"] is False


async def test_put_updates_and_reflects_on_get(client, auth_headers):
    payload = {
        "services": {"mode": "custom", "ids": [1, 2]},
        "professionals": {"mode": "all", "ids": []},
        "show_hours": True,
        "show_reviews": False,
        "show_promotions": True,
        "banner": {
            "enabled": True,
            "image_url": "https://example.com/banner.jpg",
            "title": "Promoção de inverno",
            "subtitle": None,
            "cta_label": "Agendar",
            "cta_url": "https://example.com/agendar",
        },
        "public_info": {
            "address": "Rua X, 123",
            "phone": "+5563999999999",
            "whatsapp": None,
            "instagram": "@barbearia",
            "website": None,
        },
    }
    put_resp = await client.put(
        "/admin/security/site-visibility", json=payload, headers=auth_headers
    )
    assert put_resp.status_code == 200, put_resp.text
    body = put_resp.json()
    assert body["services"] == {"mode": "custom", "ids": [1, 2]}
    assert body["show_reviews"] is False
    assert body["banner"]["title"] == "Promoção de inverno"
    assert body["updated_by_email"]

    get_resp = await client.get("/admin/security/site-visibility", headers=auth_headers)
    assert get_resp.json()["services"] == {"mode": "custom", "ids": [1, 2]}


async def test_put_requires_permission(client, reception_headers):
    payload = {
        "services": {"mode": "all", "ids": []},
        "professionals": {"mode": "all", "ids": []},
        "show_hours": True,
        "show_reviews": True,
        "show_promotions": True,
        "banner": {"enabled": False},
        "public_info": {},
    }
    resp = await client.put(
        "/admin/security/site-visibility", json=payload, headers=reception_headers
    )
    assert resp.status_code == 403


async def test_put_emits_audit_event(client, auth_headers):
    import os

    from app.db.session import AsyncSessionLocal, set_current_org
    from app.services import audit as audit_svc
    from sqlalchemy import select
    from models import AuditLog

    seed_org = int(os.environ.get("SEED_ORG_ID", "1"))
    me = await client.get("/auth/me", headers=auth_headers)
    owner_id = me.json()["user_id"]

    payload = {
        "services": {"mode": "all", "ids": []},
        "professionals": {"mode": "all", "ids": []},
        "show_hours": True,
        "show_reviews": True,
        "show_promotions": True,
        "banner": {"enabled": False},
        "public_info": {},
    }
    resp = await client.put(
        "/admin/security/site-visibility", json=payload, headers=auth_headers
    )
    assert resp.status_code == 200
    await audit_svc.wait_for_pending()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            rows = (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.organization_id == seed_org)
                    .where(AuditLog.action == "settings.site_visibility.update")
                    .where(AuditLog.actor_user_id == owner_id)
                    .order_by(AuditLog.id.desc())
                    .limit(1)
                )
            ).scalars().all()
    assert rows, "PUT de visibilidade não gravou evento de auditoria"
