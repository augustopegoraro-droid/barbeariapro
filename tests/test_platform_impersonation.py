"""Impersonação (superadmin M10 — POST /platform/orgs/{id}/impersonate).

Cobre: motivo obrigatório (422), org inexistente (404), org suspensa (409),
happy path (token de tenant FUNCIONA numa rota de tenant e carrega imp_by +
expiração curta) e auditoria em `platform_audit_log` categoria impersonation.

Requer `ADMIN_DATABASE_URL` — mesmo padrão dos demais testes de plataforma.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))
PLATFORM_EMAIL = "test-superadmin-imp@plataforma-test.com"
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
                "DELETE FROM platform_audit_log WHERE admin_id IN "
                "(SELECT id FROM platform_admins WHERE email=:e)"
            ),
            {"e": PLATFORM_EMAIL},
        )
        s.execute(text("DELETE FROM platform_admins WHERE email=:e"), {"e": PLATFORM_EMAIL})


@pytest.mark.asyncio
async def test_validacoes(client, platform_headers):
    # motivo obrigatório (curto demais → 422)
    r = await client.post(
        f"/platform/orgs/{SEED_ORG_ID}/impersonate",
        headers=platform_headers,
        json={"reason": "abc"},
    )
    assert r.status_code == 422

    r404 = await client.post(
        "/platform/orgs/999999/impersonate",
        headers=platform_headers,
        json={"reason": "chamado #123 do suporte"},
    )
    assert r404.status_code == 404


@pytest.mark.asyncio
async def test_impersonacao_happy_path_e_auditoria(client, platform_headers):
    r = await client.post(
        f"/platform/orgs/{SEED_ORG_ID}/impersonate",
        headers=platform_headers,
        json={"reason": "suporte ao chamado #4906 — reconexão do WhatsApp", "minutes": 15},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["org_id"] == SEED_ORG_ID and body["expires_in_minutes"] == 15
    assert body["impersonated_email"]

    # O token carrega imp_by e expira em ≤15 min.
    claims = jwt.decode(
        body["access_token"], settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert claims["org"] == SEED_ORG_ID and "imp_by" in claims
    assert claims["exp"] - claims["iat"] <= 15 * 60

    # O token FUNCIONA como tenant (RLS escopa a org correta)...
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    rt = await client.get("/billing/subscription", headers=headers)
    assert rt.status_code == 200, rt.text

    # ...e é rejeitado nas rotas de plataforma (isolamento bilateral).
    rp = await client.get("/platform/orgs", headers=headers)
    assert rp.status_code in (401, 403)

    # Auditoria registrada com motivo.
    ra = await client.get(
        "/platform/audit-log",
        headers=platform_headers,
        params={"category": "impersonation", "org_id": SEED_ORG_ID},
    )
    assert ra.status_code == 200
    rows = ra.json()
    assert rows and rows[0]["action"] == "impersonation_started"
    assert "4906" in (rows[0]["reason"] or "")


@pytest.mark.asyncio
async def test_org_suspensa_409(client, platform_headers):
    rs = await client.post(
        f"/platform/orgs/{SEED_ORG_ID}/suspend", headers=platform_headers
    )
    assert rs.status_code == 200
    try:
        r = await client.post(
            f"/platform/orgs/{SEED_ORG_ID}/impersonate",
            headers=platform_headers,
            json={"reason": "não deveria funcionar em suspensa"},
        )
        assert r.status_code == 409
    finally:
        ra = await client.post(
            f"/platform/orgs/{SEED_ORG_ID}/reactivate", headers=platform_headers
        )
        assert ra.status_code == 200
