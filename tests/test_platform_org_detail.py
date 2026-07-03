"""Detalhe 360° da barbearia (migration 0030 + rotas /platform/orgs/{id}/*).

Cobre:
- 404 para org inexistente; isolamento (token de tenant rejeitado).
- Shape do detalhe (cadastro + assinatura + plano + uso).
- Usuários com papel resolvido; profissionais; histórico de assinaturas.
- Notas internas: validação (vazio → 422), criação (201) + listagem + timeline.

Requer `ADMIN_DATABASE_URL` (role dona) — mesmo padrão de tests/test_platform.py.
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
PLATFORM_EMAIL = "test-superadmin-detail@plataforma-test.com"
PLATFORM_PASSWORD = "superadmin-test-123"


@pytest_asyncio.fixture
async def platform_headers(client):
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
        # Notas criadas pelo admin de teste saem junto (FK RESTRICT no admin).
        s.execute(
            text(
                "DELETE FROM platform_org_notes WHERE admin_id IN "
                "(SELECT id FROM platform_admins WHERE email=:e)"
            ),
            {"e": PLATFORM_EMAIL},
        )
        s.execute(text("DELETE FROM platform_admins WHERE email=:e"), {"e": PLATFORM_EMAIL})


@pytest.mark.asyncio
async def test_detail_org_inexistente_404(client, platform_headers):
    r = await client.get("/platform/orgs/999999", headers=platform_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_detail_token_de_tenant_rejeitado(client, auth_headers):
    r = await client.get(f"/platform/orgs/{SEED_ORG_ID}", headers=auth_headers)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_detail_shape(client, platform_headers):
    r = await client.get(f"/platform/orgs/{SEED_ORG_ID}", headers=platform_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == SEED_ORG_ID
    assert {
        "public_id", "name", "status", "subscription",
        "users_count", "barbers_count", "clients_count", "appt_30d",
        "plan_max_units", "plan_max_barbers",
    } <= set(body)
    if body["subscription"] is not None:
        assert {"id", "plan_name", "status", "current_period_end"} <= set(body["subscription"])


@pytest.mark.asyncio
async def test_detail_usuarios_com_papel(client, platform_headers):
    r = await client.get(
        f"/platform/orgs/{SEED_ORG_ID}/users", headers=platform_headers
    )
    assert r.status_code == 200, r.text
    users = r.json()
    assert len(users) >= 1
    assert {"id", "email", "is_active", "role", "roles"} <= set(users[0])
    # A org semeada tem um owner.
    assert any(u["role"] == "owner" for u in users)


@pytest.mark.asyncio
async def test_detail_profissionais_e_historico(client, platform_headers):
    rb = await client.get(
        f"/platform/orgs/{SEED_ORG_ID}/barbers", headers=platform_headers
    )
    assert rb.status_code == 200
    for b in rb.json():
        assert {"id", "name", "work_model", "deleted_at"} <= set(b)

    rs = await client.get(
        f"/platform/orgs/{SEED_ORG_ID}/subscriptions", headers=platform_headers
    )
    assert rs.status_code == 200
    subs = rs.json()
    if subs:
        assert {"id", "plan_name", "status", "created_at"} <= set(subs[0])


@pytest.mark.asyncio
async def test_notas_validacao_criacao_listagem_timeline(client, platform_headers):
    # corpo vazio → 422 (validação Pydantic)
    r = await client.post(
        f"/platform/orgs/{SEED_ORG_ID}/notes", headers=platform_headers, json={"body": ""}
    )
    assert r.status_code == 422

    # criação → 201 com autor snapshot
    r = await client.post(
        f"/platform/orgs/{SEED_ORG_ID}/notes",
        headers=platform_headers,
        json={"body": "Nota de teste do detalhe 360°"},
    )
    assert r.status_code == 201, r.text
    nota = r.json()
    assert nota["admin_email"] == PLATFORM_EMAIL
    assert nota["body"] == "Nota de teste do detalhe 360°"

    # aparece na listagem (mais recente primeiro)
    rl = await client.get(
        f"/platform/orgs/{SEED_ORG_ID}/notes", headers=platform_headers
    )
    assert rl.status_code == 200
    assert rl.json()[0]["id"] == nota["id"]

    # e na timeline unificada, junto com o evento de criação da org
    rt = await client.get(
        f"/platform/orgs/{SEED_ORG_ID}/timeline", headers=platform_headers
    )
    assert rt.status_code == 200
    kinds = {e["kind"] for e in rt.json()}
    assert "note" in kinds and "org_created" in kinds
    ats = [e["at"] for e in rt.json()]
    assert ats == sorted(ats, reverse=True)

    # nota em org inexistente → 404
    r404 = await client.post(
        "/platform/orgs/999999/notes", headers=platform_headers, json={"body": "x"}
    )
    assert r404.status_code == 404
