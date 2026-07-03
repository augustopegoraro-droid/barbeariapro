"""Onboarding da plataforma (migration 0031 + rotas /platform/onboarding*).

Cobre:
- Isolamento (sem token → 401).
- Funil agregado: shape, 11 etapas na ordem, contagens coerentes.
- Checklist por org + override manual (PUT) + volta ao automático (DELETE).
- Validações: etapa desconhecida → 422; org inexistente → 404.

Requer `ADMIN_DATABASE_URL` — mesmo padrão dos demais testes de plataforma.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.services.onboarding_progress import STAGES

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))
PLATFORM_EMAIL = "test-superadmin-onb@plataforma-test.com"
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
        s.execute(
            text(
                "DELETE FROM platform_onboarding_overrides WHERE admin_id IN "
                "(SELECT id FROM platform_admins WHERE email=:e)"
            ),
            {"e": PLATFORM_EMAIL},
        )
        s.execute(text("DELETE FROM platform_admins WHERE email=:e"), {"e": PLATFORM_EMAIL})


@pytest.mark.asyncio
async def test_onboarding_sem_token_401(client):
    r = await client.get("/platform/onboarding")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_funil_agregado_shape(client, platform_headers):
    r = await client.get("/platform/onboarding", headers=platform_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"total_orgs", "completed_orgs", "funnel", "orgs"} <= set(body)

    # 11 etapas na ordem canônica; contagens dentro de [0, total_orgs].
    assert [f["key"] for f in body["funnel"]] == [k for k, _ in STAGES]
    for f in body["funnel"]:
        assert 0 <= f["count"] <= body["total_orgs"]
    # 'conta_criada' é verdadeira para toda org ativa.
    assert body["funnel"][0]["count"] == body["total_orgs"]

    for row in body["orgs"]:
        assert {"org_id", "name", "progress_done", "progress_total", "stuck_days"} <= set(row)
        assert row["progress_done"] < row["progress_total"]  # completas não entram

    # fila ordenada por dias parada (desc)
    stuck = [r_["stuck_days"] for r_ in body["orgs"]]
    assert stuck == sorted(stuck, reverse=True)


@pytest.mark.asyncio
async def test_checklist_override_e_clear(client, platform_headers):
    url = f"/platform/orgs/{SEED_ORG_ID}/onboarding"
    r = await client.get(url, headers=platform_headers)
    assert r.status_code == 200, r.text
    base = r.json()
    assert base["progress_total"] == len(STAGES)
    by_key = {i["key"]: i for i in base["items"]}
    assert by_key["conta_criada"]["done"] is True

    # 'primeiro_acesso' não é derivável → começa pendente; marca manual → done.
    assert by_key["primeiro_acesso"]["derivable"] is False
    r_put = await client.put(
        f"{url}/primeiro_acesso", headers=platform_headers, json={"done": True}
    )
    assert r_put.status_code == 200, r_put.text
    updated = {i["key"]: i for i in r_put.json()["items"]}
    assert updated["primeiro_acesso"]["done"] is True
    assert updated["primeiro_acesso"]["source"] == "manual"
    assert r_put.json()["progress_done"] == base["progress_done"] + 1

    # DELETE volta ao automático (pendente de novo).
    r_del = await client.delete(f"{url}/primeiro_acesso", headers=platform_headers)
    assert r_del.status_code == 200
    reverted = {i["key"]: i for i in r_del.json()["items"]}
    assert reverted["primeiro_acesso"]["done"] is False
    assert reverted["primeiro_acesso"]["source"] == "auto"


@pytest.mark.asyncio
async def test_validacoes(client, platform_headers):
    r = await client.put(
        f"/platform/orgs/{SEED_ORG_ID}/onboarding/etapa_inexistente",
        headers=platform_headers,
        json={"done": True},
    )
    assert r.status_code == 422

    r2 = await client.get("/platform/orgs/999999/onboarding", headers=platform_headers)
    assert r2.status_code == 404
