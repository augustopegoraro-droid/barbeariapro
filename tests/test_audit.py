"""Auditoria (Fase 4): hash-chain, emissão automática de deny pelo guard,
permissões da tela de Auditoria e isolamento por RLS.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, set_current_org
from app.services import audit as audit_svc
from models import AuditLog

pytestmark = pytest.mark.asyncio

SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))


async def _last_events(organization_id: int, limit: int = 5):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, organization_id)
            rows = (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.organization_id == organization_id)
                    .order_by(AuditLog.id.desc())
                    .limit(limit)
                )
            ).scalars().all()
            return rows


async def test_hash_chain_links_sequential_events():
    audit_svc.record_event(
        organization_id=SEED_ORG_ID,
        action="test.chain.first",
        result="allow",
    )
    audit_svc.record_event(
        organization_id=SEED_ORG_ID,
        action="test.chain.second",
        result="allow",
    )
    await audit_svc.wait_for_pending()

    rows = await _last_events(SEED_ORG_ID, limit=2)
    assert len(rows) == 2
    newer, older = rows
    assert newer.action == "test.chain.second"
    assert older.action == "test.chain.first"
    assert newer.prev_hash == older.hash
    assert newer.hash != older.hash


async def test_guard_deny_is_audited(client, barber_headers):
    me = await client.get("/auth/me", headers=barber_headers)
    assert me.status_code == 200
    barber_id = me.json()["user_id"]

    resp = await client.get(
        "/financeiro", params={"date": "2026-07-01"}, headers=barber_headers
    )
    assert resp.status_code == 403
    await audit_svc.wait_for_pending()

    rows = await _last_events(SEED_ORG_ID, limit=10)
    deny_rows = [
        r for r in rows
        if r.result == "deny" and r.actor_user_id == barber_id
    ]
    assert deny_rows, "guard não gravou o deny em audit_logs"
    assert "finance" in deny_rows[0].action


async def test_guard_dependency_deny_captures_ip_and_ua(client, reception_headers):
    """Cobre o caminho `Depends(require(...))` (dependência de rota, distinto do
    `require_permission` imperativo já coberto acima) — só ele tem acesso ao
    `Request` para IP/UA."""
    me = await client.get("/auth/me", headers=reception_headers)
    reception_id = me.json()["user_id"]

    resp = await client.get(
        "/integracoes/whatsapp/qr",
        headers={**reception_headers, "User-Agent": "pytest-audit-agent"},
    )
    assert resp.status_code == 403
    await audit_svc.wait_for_pending()

    rows = await _last_events(SEED_ORG_ID, limit=10)
    deny_rows = [
        r for r in rows
        if r.result == "deny" and r.actor_user_id == reception_id
        and "integrations.whatsapp.manage" in r.action
    ]
    assert deny_rows, "Depends(require(...)) não gravou o deny em audit_logs"
    assert deny_rows[0].user_agent == "pytest-audit-agent"
    assert deny_rows[0].ip


async def test_audit_list_requires_permission(client, reception_headers):
    resp = await client.get("/admin/security/audit", headers=reception_headers)
    assert resp.status_code == 403


async def test_audit_list_allowed_for_owner(client, auth_headers):
    resp = await client.get("/admin/security/audit", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body and "total" in body
    assert body["total"] >= 1


async def test_audit_export_requires_permission(client, reception_headers):
    resp = await client.get("/admin/security/audit/export.csv", headers=reception_headers)
    assert resp.status_code == 403


async def test_audit_export_emits_self_event(client, auth_headers):
    me = await client.get("/auth/me", headers=auth_headers)
    owner_id = me.json()["user_id"]

    resp = await client.get("/admin/security/audit/export.csv", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    await audit_svc.wait_for_pending()

    rows = await _last_events(SEED_ORG_ID, limit=5)
    export_rows = [
        r for r in rows
        if r.action == "security.audit.export" and r.actor_user_id == owner_id
    ]
    assert export_rows, "exportação da auditoria não auditou a si mesma"


async def test_rls_hides_row_from_other_org_context():
    audit_svc.record_event(
        organization_id=SEED_ORG_ID,
        action="test.rls.marker",
        result="allow",
    )
    await audit_svc.wait_for_pending()

    rows = await _last_events(SEED_ORG_ID, limit=1)
    marker_id = rows[0].id
    assert rows[0].action == "test.rls.marker"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, 999_999_999)
            hidden = (
                await session.execute(
                    select(AuditLog).where(AuditLog.id == marker_id)
                )
            ).scalar_one_or_none()
            assert hidden is None
