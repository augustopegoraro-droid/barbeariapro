"""Painel de plataforma / superadmin (migration 0021 + app/api/platform.py).

Cobre:
- Sem token → 401 em /platform/*.
- Token de TENANT em /platform/* → 401 (discriminador `typ`).
- Login de plataforma + listagem de orgs (200).
- Onboarding (`POST /platform/orgs`) cria org + owner + seed; o owner novo
  consegue logar via `/auth/login` (prova o seed completo).
- Dashboard com MRR consolidado.

Requer `ADMIN_DATABASE_URL` (role dona) para semear o superadmin e limpar a org
de teste — `pytest.skip` se ausente (mesmo padrão dos demais testes de integração).
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.security import hash_password

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
PLATFORM_EMAIL = "test-superadmin@plataforma-test.com"
PLATFORM_PASSWORD = "superadmin-test-123"


def _owner_engine():
    if not ADMIN_URL:
        pytest.skip("ADMIN_DATABASE_URL ausente — testes de plataforma exigem role dona.")
    return create_engine(ADMIN_URL)


def _purge_org(org_id: int) -> None:
    """Hard-delete de uma org de teste (ordem de FK), via role dona (bypassa RLS)."""
    eng = create_engine(ADMIN_URL)  # ADMIN_URL já validado pelo caller
    stmts = [
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
async def platform_headers(client):
    """Semeia um superadmin (role dona) e devolve o header Bearer de plataforma."""
    eng = _owner_engine()
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


# ─── auth / isolamento ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sem_token_401(client):
    for path in ("/platform/orgs", "/platform/dashboard"):
        r = await client.get(path)
        assert r.status_code in (401, 403), f"{path} → {r.status_code}"


@pytest.mark.asyncio
async def test_token_de_tenant_nao_acessa_plataforma(client, auth_headers):
    """Token de TENANT (com `org`, sem `typ`) deve ser rejeitado em /platform/*."""
    r = await client.get("/platform/orgs", headers=auth_headers)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_login_invalido_401(client, platform_headers):
    r = await client.post(
        "/platform/auth/login",
        json={"email": PLATFORM_EMAIL, "password": "errada"},
    )
    assert r.status_code == 401


# ─── leitura ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lista_orgs_ok(client, platform_headers):
    r = await client.get("/platform/orgs", headers=platform_headers)
    assert r.status_code == 200, r.text
    orgs = r.json()
    assert isinstance(orgs, list) and len(orgs) >= 1
    assert {"id", "name", "status"} <= set(orgs[0].keys())


@pytest.mark.asyncio
async def test_dashboard_mrr_consolidado(client, platform_headers):
    r = await client.get("/platform/dashboard", headers=platform_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # MRR do SaaS (Plan.price_month) e MRR das mensalidades dos clientes finais
    # são números distintos e ambos presentes.
    assert "saas_mrr" in body and body["saas_mrr"] >= 0
    assert "tenants_membership_mrr" in body and body["tenants_membership_mrr"] >= 0
    assert "tenants_active_memberships" in body
    assert {"total", "active", "trial", "suspended"} <= set(body["counts"].keys())
    assert isinstance(body["usage"], list)


# ─── onboarding ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cria_org_com_owner_e_seed(client, platform_headers):
    """POST /platform/orgs cria org + owner + serviços; o owner novo loga."""
    if not ADMIN_URL:
        pytest.skip("ADMIN_DATABASE_URL ausente.")
    plan_id = _first_plan_id()
    owner_email = "owner-novo@plataforma-test.com"
    payload = {
        "name": "Barbearia Teste Plataforma",
        "subdomain": "teste-plataforma-xyz",
        "plan_id": plan_id,
        "owner_email": owner_email,
        "owner_password": "ownernovo123",
    }
    org_id = None
    try:
        r = await client.post("/platform/orgs", headers=platform_headers, json=payload)
        assert r.status_code == 201, r.text
        out = r.json()
        org_id = out["org_id"]
        assert out["services"] == 15 and out["unit_id"] and out["owner_user_id"]

        # aparece na listagem
        rl = await client.get("/platform/orgs", headers=platform_headers)
        assert any(o["id"] == org_id for o in rl.json())

        # o owner recém-criado consegue logar (prova o seed completo)
        rlogin = await client.post(
            "/auth/login",
            json={
                "organization_id": org_id,
                "email": owner_email,
                "password": "ownernovo123",
            },
        )
        assert rlogin.status_code == 200, rlogin.text
        assert rlogin.json()["role"] == "owner"

        login_body = {
            "organization_id": org_id,
            "email": owner_email,
            "password": "ownernovo123",
        }

        # suspend → login do tenant é bloqueado (suspensão não é cosmética)
        rs = await client.post(f"/platform/orgs/{org_id}/suspend", headers=platform_headers)
        assert rs.status_code == 200 and rs.json()["status"] == "suspended"
        rsusp = await client.post("/auth/login", json=login_body)
        assert rsusp.status_code == 403, rsusp.text

        # reactivate → login volta a funcionar
        ra = await client.post(f"/platform/orgs/{org_id}/reactivate", headers=platform_headers)
        assert ra.status_code == 200 and ra.json()["status"] != "suspended"
        rreact = await client.post("/auth/login", json=login_body)
        assert rreact.status_code == 200, rreact.text
    finally:
        if org_id is not None:
            _purge_org(org_id)


def _first_plan_id() -> int:
    eng = create_engine(ADMIN_URL)
    with Session(eng) as s:
        pid = s.execute(text("SELECT id FROM plans ORDER BY id LIMIT 1")).scalar_one_or_none()
    if pid is None:
        pytest.skip("Nenhum plano cadastrado (rode scripts/seed.py).")
    return int(pid)
