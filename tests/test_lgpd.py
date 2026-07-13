"""Direitos do titular (Fase 8): permissão, exportação, anonimização e histórico de consentimento."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def _create_disposable_client(client, auth_headers) -> int:
    suf = uuid.uuid4().int % 100000
    resp = await client.post(
        "/clientes",
        headers=auth_headers,
        json={"name": "Titular LGPD Teste", "phone": f"6398{suf:05d}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_export_requires_permission(client, manager_headers, auth_headers):
    client_id = await _create_disposable_client(client, auth_headers)
    resp = await client.get(
        f"/admin/security/lgpd/clients/{client_id}/export", headers=manager_headers
    )
    assert resp.status_code == 403


async def test_export_returns_client_data(client, auth_headers):
    client_id = await _create_disposable_client(client, auth_headers)
    resp = await client.get(
        f"/admin/security/lgpd/clients/{client_id}/export", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["cliente"]["id"] == client_id
    assert body["cliente"]["nome"] == "Titular LGPD Teste"
    assert "agendamentos" in body and "consentimentos" in body


async def test_export_404_for_unknown_client(client, auth_headers):
    resp = await client.get(
        "/admin/security/lgpd/clients/999999999/export", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_anonymize_requires_permission(client, manager_headers, auth_headers):
    client_id = await _create_disposable_client(client, auth_headers)
    resp = await client.post(
        f"/admin/security/lgpd/clients/{client_id}/anonymize", headers=manager_headers
    )
    assert resp.status_code == 403


async def test_anonymize_scrubs_pii(client, auth_headers):
    client_id = await _create_disposable_client(client, auth_headers)

    resp = await client.post(
        f"/admin/security/lgpd/clients/{client_id}/anonymize", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["client_id"] == client_id
    assert body["anonymized_at"]

    export_resp = await client.get(
        f"/admin/security/lgpd/clients/{client_id}/export", headers=auth_headers
    )
    exported = export_resp.json()["cliente"]
    assert exported["nome"] == "Cliente anonimizado"
    assert exported["telefone"] != ""
    assert exported["anonimizado_em"]


async def test_anonymize_emits_audit_event(client, auth_headers):
    import os

    from app.db.session import AsyncSessionLocal, set_current_org
    from app.services import audit as audit_svc
    from sqlalchemy import select
    from models import AuditLog

    seed_org = int(os.environ.get("SEED_ORG_ID", "1"))
    client_id = await _create_disposable_client(client, auth_headers)

    resp = await client.post(
        f"/admin/security/lgpd/clients/{client_id}/anonymize", headers=auth_headers
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
                    .where(AuditLog.action == "privacy.lgpd.anonymize")
                    .where(AuditLog.resource_id == str(client_id))
                    .limit(1)
                )
            ).scalars().all()
    assert rows, "anonimização não gravou evento de auditoria"


async def test_opt_out_records_consent_history(client, auth_headers):
    """`register_opt_out` (app/services/opt_out.py) passa a gravar em
    consent_records além de atualizar client_consents (D-51)."""
    import os

    from app.db.session import AsyncSessionLocal, set_current_org
    from app.services.opt_out import register_opt_out

    seed_org = int(os.environ.get("SEED_ORG_ID", "1"))
    client_id = await _create_disposable_client(client, auth_headers)

    me = await client.get(f"/admin/security/lgpd/clients/{client_id}/export", headers=auth_headers)
    phone = me.json()["cliente"]["telefone"]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            result = await register_opt_out(session, org_id=seed_org, phone=phone)
    assert result == client_id

    consents_resp = await client.get(
        f"/admin/security/lgpd/clients/{client_id}/consents", headers=auth_headers
    )
    assert consents_resp.status_code == 200
    rows = consents_resp.json()
    assert any(r["status"] == "opt_out" and r["channel"] == "whatsapp" for r in rows)
