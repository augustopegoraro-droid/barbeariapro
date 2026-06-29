"""Resolução de tenant multi-tenant (migration 0020 + app/services/tenant.py).

Cobre:
- `GET /auth/tenant?subdomain=` (pré-login): happy path, case-insensitive, 404.
- `org_id_by_subdomain` / `org_id_by_wa_instance` (funções SECURITY DEFINER).
- `get_bot_db` resolvendo a org pela instância (header `X-Instance`), com
  fallback ao `settings.bot_organization_id` quando a instância não mapeia.

Os campos `subdomain`/`wa_instance_name` são setados na org semeada e revertidos
no teardown (não dependem de seed prévio).
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from app.services.tenant import org_id_by_subdomain, org_id_by_wa_instance

SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))
_SUB = "test-tenant-resolution"
_INSTANCE = "test-instance-resolution"


@pytest_asyncio.fixture
async def tenant_fields():
    """Seta subdomain/wa_instance_name na org semeada e reverte no fim."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            res = await s.execute(
                text(
                    "UPDATE organizations SET subdomain=:sub, wa_instance_name=:inst "
                    "WHERE id=:id"
                ),
                {"sub": _SUB, "inst": _INSTANCE, "id": SEED_ORG_ID},
            )
            if res.rowcount == 0:
                pytest.skip("Org semeada indisponível (rode scripts/seed.py).")
    yield SEED_ORG_ID
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            await s.execute(
                text(
                    "UPDATE organizations SET subdomain=NULL, wa_instance_name=NULL "
                    "WHERE id=:id"
                ),
                {"id": SEED_ORG_ID},
            )


# ─── GET /auth/tenant (pré-login) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_endpoint_resolve_ok(client, tenant_fields):
    resp = await client.get("/auth/tenant", params={"subdomain": _SUB})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["organization_id"] == SEED_ORG_ID
    assert body["name"]


@pytest.mark.asyncio
async def test_tenant_endpoint_case_insensitive(client, tenant_fields):
    resp = await client.get("/auth/tenant", params={"subdomain": _SUB.upper()})
    assert resp.status_code == 200
    assert resp.json()["organization_id"] == SEED_ORG_ID


@pytest.mark.asyncio
async def test_tenant_endpoint_desconhecido_404(client, tenant_fields):
    resp = await client.get("/auth/tenant", params={"subdomain": "nao-existe-xyz"})
    assert resp.status_code == 404


# ─── funções SECURITY DEFINER (resolução pré-tenant, sem RLS) ──────────────────

@pytest.mark.asyncio
async def test_org_id_by_subdomain_e_instance(tenant_fields):
    # Sessão SEM tenant: a função SQL ignora a RLS e devolve só o id.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            assert await org_id_by_subdomain(s, _SUB) == SEED_ORG_ID
            assert await org_id_by_subdomain(s, _SUB.upper()) == SEED_ORG_ID
            assert await org_id_by_subdomain(s, "nada") is None
            assert await org_id_by_wa_instance(s, _INSTANCE) == SEED_ORG_ID
            assert await org_id_by_wa_instance(s, "nada") is None


# ─── get_bot_db: org pela instância (header X-Instance) ────────────────────────

@pytest.mark.asyncio
async def test_bot_resolve_org_por_instancia(client, tenant_fields):
    """Endpoint do bot com X-Instance mapeada resolve a org da instância."""
    if not settings.bot_api_key:
        pytest.skip("BOT_API_KEY não configurado neste ambiente.")
    headers = {"X-Bot-Token": settings.bot_api_key, "X-Instance": _INSTANCE}
    resp = await client.get("/bot/barbers", headers=headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_bot_instancia_desconhecida_cai_no_fallback(client, tenant_fields):
    """Instância sem mapeamento → fallback a settings.bot_organization_id."""
    if not settings.bot_api_key or not settings.bot_organization_id:
        pytest.skip("Bot single-tenant não configurado neste ambiente.")
    headers = {"X-Bot-Token": settings.bot_api_key, "X-Instance": "instancia-inexistente"}
    resp = await client.get("/bot/barbers", headers=headers)
    assert resp.status_code == 200, resp.text
