"""Central de Operações + auditoria (migration 0034 + /platform/alerts|audit-log).

Cobre: isolamento (401), shape dos alertas (severidades ordenadas, contadores),
auditoria gravada por suspend/reactivate e lida com filtro de categoria.

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
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))
PLATFORM_EMAIL = "test-superadmin-alerts@plataforma-test.com"
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
async def test_alertas_sem_token_401(client):
    for path in ("/platform/alerts", "/platform/audit-log"):
        r = await client.get(path)
        assert r.status_code in (401, 403), path


@pytest.mark.asyncio
async def test_alertas_shape_e_ordenacao(client, platform_headers):
    r = await client.get("/platform/alerts", headers=platform_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"counts", "alerts"} <= set(body)
    sev_order = {"critical": 0, "warning": 1, "info": 2}
    sevs = [sev_order[a["severity"]] for a in body["alerts"]]
    assert sevs == sorted(sevs)
    for a in body["alerts"]:
        assert {"severity", "kind", "title"} <= set(a)


@pytest.mark.asyncio
async def test_auditoria_gravada_e_filtrada(client, platform_headers):
    # suspend + reactivate geram duas linhas de auditoria categoria 'org'.
    rs = await client.post(
        f"/platform/orgs/{SEED_ORG_ID}/suspend", headers=platform_headers
    )
    assert rs.status_code == 200, rs.text
    ra = await client.post(
        f"/platform/orgs/{SEED_ORG_ID}/reactivate", headers=platform_headers
    )
    assert ra.status_code == 200, ra.text

    r = await client.get(
        "/platform/audit-log",
        headers=platform_headers,
        params={"category": "org", "org_id": SEED_ORG_ID, "limit": 10},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    actions = [x["action"] for x in rows]
    assert "org_reactivated" in actions and "org_suspended" in actions
    assert rows[0]["admin_email"] == PLATFORM_EMAIL
    assert all(x["category"] == "org" for x in rows)

    # categoria inexistente → lista vazia (sem erro)
    r2 = await client.get(
        "/platform/audit-log", headers=platform_headers,
        params={"category": "security", "org_id": SEED_ORG_ID},
    )
    assert r2.status_code == 200
