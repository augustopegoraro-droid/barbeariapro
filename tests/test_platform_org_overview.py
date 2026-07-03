"""Gestão de barbearias (migration 0029 + GET /platform/orgs/overview).

Cobre:
- Isolamento (sem token / token de tenant → 401).
- Shape rico da linha + envelope de paginação + counts por status.
- Busca `q`, filtro `status`, paginação `per_page` e `order` inválido → 422.

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
PLATFORM_EMAIL = "test-superadmin-overview@plataforma-test.com"
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
        s.execute(text("DELETE FROM platform_admins WHERE email=:e"), {"e": PLATFORM_EMAIL})


@pytest.mark.asyncio
async def test_overview_sem_token_401(client):
    r = await client.get("/platform/orgs/overview")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_overview_token_de_tenant_rejeitado(client, auth_headers):
    r = await client.get("/platform/orgs/overview", headers=auth_headers)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_overview_shape_e_counts(client, platform_headers):
    r = await client.get("/platform/orgs/overview", headers=platform_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"items", "total", "page", "per_page", "counts"} <= set(body)
    assert body["total"] >= 1 and len(body["items"]) >= 1

    row = body["items"][0]
    assert {
        "id", "name", "subdomain", "plan_id", "plan_name", "plan_price_month",
        "status", "sub_period_end", "created_at", "deleted_at",
        "users_count", "barbers_count", "clients_count", "appt_30d", "last_activity",
    } <= set(row)
    for f in ("users_count", "barbers_count", "clients_count", "appt_30d"):
        assert row[f] >= 0

    # counts (pré-filtro) devem somar o total de orgs da listagem clássica.
    rl = await client.get("/platform/orgs", headers=platform_headers)
    assert sum(body["counts"].values()) == len(rl.json())

    # ordenação default por nome (case-insensitive)
    names = [i["name"].lower() for i in body["items"]]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_overview_busca_e_filtros(client, platform_headers):
    base = (await client.get("/platform/orgs/overview", headers=platform_headers)).json()
    alvo = base["items"][0]

    # busca por trecho do nome encontra o alvo
    r = await client.get(
        "/platform/orgs/overview",
        headers=platform_headers,
        params={"q": alvo["name"][:4]},
    )
    assert any(i["id"] == alvo["id"] for i in r.json()["items"])

    # busca por id exato
    r = await client.get(
        "/platform/orgs/overview", headers=platform_headers, params={"q": str(alvo["id"])}
    )
    assert any(i["id"] == alvo["id"] for i in r.json()["items"])

    # filtro por status devolve só o status pedido (total coerente com counts)
    r = await client.get(
        "/platform/orgs/overview",
        headers=platform_headers,
        params={"status": alvo["status"]},
    )
    body = r.json()
    assert all(i["status"] == alvo["status"] for i in body["items"])
    assert body["total"] == base["counts"].get(alvo["status"], 0)


@pytest.mark.asyncio
async def test_overview_paginacao_e_order(client, platform_headers):
    r = await client.get(
        "/platform/orgs/overview",
        headers=platform_headers,
        params={"per_page": 1, "page": 1},
    )
    body = r.json()
    assert len(body["items"]) == 1 and body["per_page"] == 1

    r2 = await client.get(
        "/platform/orgs/overview",
        headers=platform_headers,
        params={"order": "-created_at"},
    )
    assert r2.status_code == 200

    r3 = await client.get(
        "/platform/orgs/overview",
        headers=platform_headers,
        params={"order": "campo_invalido"},
    )
    assert r3.status_code == 422
