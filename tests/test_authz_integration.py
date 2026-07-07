"""Testes de integração do RBAC por permissões (ASGI + DB semeado).

Cobrem: /auth/me/permissions por papel, e as correções V4/V5/V6/V7 batendo nos
endpoints reais como owner/manager/reception/barber. Skip automático se o DB não
estiver semeado (mesmo padrão dos demais testes de integração).
"""

from __future__ import annotations

import pytest

from app.core.permissions import ALL_CODES

pytestmark = pytest.mark.asyncio


# ─── /auth/me/permissions por papel ─────────────────────────────────────────────
async def test_me_permissions_owner_has_all(client, auth_headers):
    r = await client.get("/auth/me/permissions", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "owner"
    assert set(body["permissions"]) == set(ALL_CODES)


async def test_me_permissions_reception(client, reception_headers):
    r = await client.get("/auth/me/permissions", headers=reception_headers)
    assert r.status_code == 200
    perms = set(r.json()["permissions"])
    assert "reports.dashboard.financial.view" not in perms  # V5
    assert "integrations.whatsapp.manage" not in perms       # V6
    assert "finance.revenue.view" not in perms
    assert "reports.dashboard.view" in perms
    assert "clients.bot_pause" in perms


async def test_me_permissions_barber(client, barber_headers):
    r = await client.get("/auth/me/permissions", headers=barber_headers)
    assert r.status_code == 200
    perms = set(r.json()["permissions"])
    assert "conversations.stream" not in perms   # V4
    assert "clients.bot_pause" not in perms       # V7
    assert "finance.revenue.view" not in perms
    assert "schedule.own.view" in perms


# ─── V5 — dashboard financeiro redigido para a recepção ─────────────────────────
async def test_dashboard_redacts_financials_for_reception(client, reception_headers):
    r = await client.get("/dashboard", params={"period": "30d"}, headers=reception_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["total_revenue"] == 0.0
    assert d["avg_ticket"] == 0.0
    assert all(b["revenue"] == 0.0 and b["commission"] == 0.0 for b in d["barbers"])
    assert all(s["revenue"] == 0.0 for s in d["top_services"])
    assert all(dp["revenue"] == 0.0 for dp in d["daily"])


async def test_dashboard_accessible_to_owner(client, auth_headers):
    r = await client.get("/dashboard", params={"period": "30d"}, headers=auth_headers)
    assert r.status_code == 200


# ─── V6 — QR/status do WhatsApp exigem permissão ────────────────────────────────
async def test_whatsapp_qr_forbidden_for_reception(client, reception_headers):
    r = await client.get("/integracoes/whatsapp/qr", headers=reception_headers)
    assert r.status_code == 403


async def test_whatsapp_qr_not_forbidden_for_owner(client, auth_headers):
    # owner passa o guard; sem Evolution configurada o handler devolve 503 (não 403).
    r = await client.get("/integracoes/whatsapp/qr", headers=auth_headers)
    assert r.status_code != 403


async def test_whatsapp_status_forbidden_for_barber(client, barber_headers):
    r = await client.get("/integracoes/whatsapp/status", headers=barber_headers)
    assert r.status_code == 403


# ─── V7 — bot-pause exige permissão ─────────────────────────────────────────────
async def test_bot_pause_forbidden_for_barber(client, barber_headers):
    # o guard nega antes de tocar no cliente → 403 independe do id existir.
    r = await client.patch(
        "/clientes/1/bot-pause", params={"paused": True}, headers=barber_headers
    )
    assert r.status_code == 403


# ─── V4 — SSE stream exige permissão (barbeiro é barrado) ───────────────────────
async def test_stream_forbidden_for_barber(client, barber_headers):
    token = barber_headers["Authorization"].split(" ", 1)[1]
    r = await client.get("/crm/stream", params={"token": token})
    assert r.status_code == 403
