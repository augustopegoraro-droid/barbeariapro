"""Testes do router OAuth de integrações (app/api/integracoes.py).

Estratégia:
- authorize: usa o cliente ASGI (sem rede) com JWT de owner/barber.
- callback: mocka exchange_code para não tocar o Google real.
- Sem chamada real ao Google nem escrita em banco de produção.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import pytest_asyncio

from app.api.integracoes import _build_state, _verify_state
from app.core.config import settings
from app.core.crypto import decrypt_token


# ─── fixtures extras ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def barber_headers(client):
    """Header de autenticação para um usuário com role barber (marciana)."""
    seed_org = int(os.environ.get("SEED_ORG_ID", "3"))
    resp = await client.post(
        "/auth/login",
        json={"email": "marciana@barbeariapro.com", "password": "senha123", "organization_id": seed_org},
    )
    if resp.status_code != 200:
        pytest.skip("DB não semeado — pule este teste")
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ─── helpers de state (unitários, sem DB/rede) ────────────────────────────────

def test_state_round_trip():
    state = _build_state(org_id=42)
    assert _verify_state(state) == 42


def test_state_expirado(monkeypatch):
    from app.api import integracoes as mod
    monkeypatch.setattr(mod, "_STATE_TTL_SECONDS", -1)
    state = _build_state(org_id=7)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _verify_state(state)
    assert exc.value.status_code == 400


def test_state_adulterado():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _verify_state("token.adulterado.aqui")
    assert exc.value.status_code == 400


# ─── GET /integracoes/google/calendar/authorize ───────────────────────────────

@pytest.mark.asyncio
async def test_authorize_redireciona_para_google(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost:8001/cb")

    resp = await client.get(
        "/integracoes/google/calendar/authorize",
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    q = parse_qs(urlparse(loc).query)
    assert q["response_type"] == ["code"]
    assert q["access_type"] == ["offline"]
    assert "state" in q


@pytest.mark.asyncio
async def test_authorize_sem_config_google_503(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_redirect_uri", "")

    resp = await client.get(
        "/integracoes/google/calendar/authorize",
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_authorize_barber_403(client, barber_headers, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost:8001/cb")

    resp = await client.get(
        "/integracoes/google/calendar/authorize",
        headers=barber_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_authorize_sem_jwt_401(client):
    resp = await client.get(
        "/integracoes/google/calendar/authorize",
        follow_redirects=False,
    )
    assert resp.status_code in (401, 403)  # HTTPBearer sem header → 403; sem scheme → 401


# ─── GET /integracoes/google/calendar/callback ────────────────────────────────

@pytest.mark.asyncio
async def test_callback_sem_code_400(client):
    state = _build_state(org_id=1)
    resp = await client.get(f"/integracoes/google/calendar/callback?state={state}")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_callback_error_param_400(client):
    state = _build_state(org_id=1)
    resp = await client.get(
        f"/integracoes/google/calendar/callback?error=access_denied&state={state}"
    )
    assert resp.status_code == 400
    assert "access_denied" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_callback_state_invalido_400(client):
    resp = await client.get(
        "/integracoes/google/calendar/callback?code=abc&state=invalido"
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_callback_persiste_integration_account(client, monkeypatch):
    """Troca de code bem-sucedida → cria/atualiza IntegrationAccount na org."""
    from cryptography.fernet import Fernet
    from sqlalchemy import select
    from models.integration import IntegrationAccount
    from models.enums import IntegrationProvider
    from app.db.session import AsyncSessionLocal, set_current_org
    from app.core import crypto

    seed_org = int(os.environ.get("SEED_ORG_ID", "3"))

    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost:8001/cb")
    monkeypatch.setattr(settings, "google_frontend_success_url", "")  # força retorno JSON
    monkeypatch.setattr(settings, "token_encryption_key", Fernet.generate_key().decode())
    crypto._fernet_for.cache_clear()

    async def fake_exchange(code, *, client=None):
        return {"access_token": "at-test-123", "refresh_token": "rt-test-456", "expires_in": 3599}

    with patch("app.services.google_calendar.exchange_code", side_effect=fake_exchange):
        state = _build_state(org_id=seed_org)
        resp = await client.get(
            f"/integracoes/google/calendar/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            row = (
                await session.execute(
                    select(IntegrationAccount)
                    .where(
                        IntegrationAccount.organization_id == seed_org,
                        IntegrationAccount.provider == IntegrationProvider.google_calendar,
                    )
                    .order_by(IntegrationAccount.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    assert row is not None
    assert decrypt_token(row.token_encrypted) == "at-test-123"
    assert decrypt_token(row.refresh_token_encrypted) == "rt-test-456"
    crypto._fernet_for.cache_clear()


@pytest.mark.asyncio
async def test_callback_google_error_502(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost:8001/cb")

    from app.services.google_calendar import GoogleCalendarError

    async def fail_exchange(code, *, client=None):
        raise GoogleCalendarError("invalid_grant")

    with patch("app.services.google_calendar.exchange_code", side_effect=fail_exchange):
        state = _build_state(org_id=1)
        resp = await client.get(
            f"/integracoes/google/calendar/callback?code=bad&state={state}"
        )

    assert resp.status_code == 502
