"""Onboarding da connected account (Stripe Connect, Feature 2).

Roda com o provider MOCKADO (`registry` devolve `MockConnectProvider` enquanto
`CONNECT_ENABLED=False`), então nenhuma chave real é necessária. Os testes que
exercitam o caminho feliz ligam `settings.connect_enabled` via monkeypatch —
sem `stripe_connect_secret_key`, o registry continua devolvendo o mock.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from models import Organization
from tests.conftest import SEED_ORG_ID


@pytest.fixture
def connect_on(monkeypatch):
    """Liga a feature SEM chave real → provider mockado."""
    monkeypatch.setattr(settings, "connect_enabled", True)
    monkeypatch.setattr(settings, "stripe_connect_secret_key", "")
    monkeypatch.setattr(settings, "stripe_connect_publishable_key", "pk_test_mock")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_org_connect():
    """Zera os campos de Connect da org semeada antes e depois de cada teste."""
    await _clear()
    yield
    await _clear()


async def _clear() -> None:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            org = (
                await s.execute(select(Organization).where(Organization.id == SEED_ORG_ID))
            ).scalar_one_or_none()
            if org is None:
                return
            org.stripe_connected_account_id = None
            org.stripe_connect_charges_enabled = False
            org.stripe_connect_payouts_enabled = False
            org.stripe_connect_details_submitted = False
            org.stripe_connect_synced_at = None
            org.platform_fee_pct = None


# ─── kill switch ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_reflete_kill_switch_desligado(client, auth_headers):
    resp = await client.get("/connect/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["has_account"] is False
    assert body["charges_enabled"] is False


@pytest.mark.asyncio
async def test_criar_conta_com_feature_desligada_503(client, auth_headers):
    """503 coerente (recurso indisponível), nunca 500 nem conta criada à toa."""
    resp = await client.post("/connect/account", headers=auth_headers)
    assert resp.status_code == 503

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        org = (
            await s.execute(select(Organization).where(Organization.id == SEED_ORG_ID))
        ).scalar_one()
        assert org.stripe_connected_account_id is None


# ─── RBAC ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_cria_conta_gerente_nao(client, auth_headers, manager_headers, connect_on):
    """`billing.manage` é owner-only: mexer em conta bancária não é do gerente."""
    negado = await client.post("/connect/account", headers=manager_headers)
    assert negado.status_code == 403

    permitido = await client.post("/connect/account", headers=auth_headers)
    assert permitido.status_code == 200, permitido.text
    assert permitido.json()["account_id"] == f"acct_mock_{SEED_ORG_ID}"


@pytest.mark.asyncio
async def test_barbeiro_nao_ve_status(client, barber_headers):
    resp = await client.get("/connect/status", headers=barber_headers)
    assert resp.status_code == 403


# ─── idempotência ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_account_e_idempotente(client, auth_headers, connect_on):
    primeira = await client.post("/connect/account", headers=auth_headers)
    segunda = await client.post("/connect/account", headers=auth_headers)
    assert primeira.status_code == segunda.status_code == 200
    assert primeira.json()["account_id"] == segunda.json()["account_id"]

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        org = (
            await s.execute(select(Organization).where(Organization.id == SEED_ORG_ID))
        ).scalar_one()
        assert org.stripe_connected_account_id == primeira.json()["account_id"]


# ─── sessão embutida / sync ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_session_exige_conta(client, auth_headers, connect_on):
    sem_conta = await client.post("/connect/account-session", headers=auth_headers)
    assert sem_conta.status_code == 422

    await client.post("/connect/account", headers=auth_headers)
    com_conta = await client.post("/connect/account-session", headers=auth_headers)
    assert com_conta.status_code == 200, com_conta.text
    assert com_conta.json()["client_secret"].startswith("acs_secret_mock_")
    assert com_conta.json()["publishable_key"] == "pk_test_mock"


@pytest.mark.asyncio
async def test_sync_copia_flags_e_invalida_cache(client, auth_headers, connect_on, monkeypatch):
    chamadas: list[tuple[int, list[str]]] = []

    async def _spy(org_id: int, tags: list[str]) -> None:
        chamadas.append((org_id, tags))

    monkeypatch.setattr("app.api.connect.invalidate_public_tags", _spy)

    await client.post("/connect/account", headers=auth_headers)
    resp = await client.post("/connect/sync", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["charges_enabled"] is True
    assert body["details_submitted"] is True

    # `charges_enabled` mudou (false → true) → vitrine e planos invalidados
    assert chamadas == [(SEED_ORG_ID, ["public-info", "public-plans"])]

    # 2ª sincronização não muda nada → não reinvalida
    await client.post("/connect/sync", headers=auth_headers)
    assert len(chamadas) == 1


@pytest.mark.asyncio
async def test_sync_sem_conta_422(client, auth_headers, connect_on):
    resp = await client.post("/connect/sync", headers=auth_headers)
    assert resp.status_code == 422
