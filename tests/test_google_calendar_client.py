"""Testes do cliente Google Calendar / OAuth (app/services/google_calendar.py).

Sem rede: usa httpx.MockTransport para simular as respostas do Google.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx
import pytest

from app.core.config import settings
from app.services import google_calendar as gc


@pytest.fixture
def oauth_cfg(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "secret-xyz")
    monkeypatch.setattr(
        settings,
        "google_redirect_uri",
        "http://localhost:8001/integracoes/google/calendar/callback",
    )


def _mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ─── build_authorization_url (puro, sem rede) ──────────────────────────────────

def test_build_authorization_url(oauth_cfg):
    url = gc.build_authorization_url(state="org=1.sig=abc")
    assert url.startswith(gc.GOOGLE_AUTH_URI + "?")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid.apps.googleusercontent.com"]
    assert q["response_type"] == ["code"]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["org=1.sig=abc"]
    assert q["scope"] == [settings.google_calendar_scopes]
    assert q["redirect_uri"] == [settings.google_redirect_uri]


def test_build_authorization_url_scope_customizado(oauth_cfg):
    url = gc.build_authorization_url(state="s", scopes="scope-a scope-b")
    q = parse_qs(urlparse(url).query)
    assert q["scope"] == ["scope-a scope-b"]


def test_build_authorization_url_sem_config_levanta(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(gc.GoogleCalendarError):
        gc.build_authorization_url(state="x")


# ─── OAuth token endpoint ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exchange_code(oauth_cfg):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(
            200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3599}
        )

    async with _mock_client(handler) as c:
        tok = await gc.exchange_code("auth-code-123", client=c)

    assert tok["access_token"] == "at-1"
    assert tok["refresh_token"] == "rt-1"
    assert captured["url"] == gc.GOOGLE_TOKEN_URI
    assert "grant_type=authorization_code" in captured["body"]
    assert "code=auth-code-123" in captured["body"]


@pytest.mark.asyncio
async def test_exchange_code_sem_config_levanta(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    with pytest.raises(gc.GoogleCalendarError):
        await gc.exchange_code("x")


@pytest.mark.asyncio
async def test_refresh_access_token(oauth_cfg):
    def handler(request):
        assert "grant_type=refresh_token" in request.content.decode()
        return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3599})

    async with _mock_client(handler) as c:
        tok = await gc.refresh_access_token("rt-1", client=c)
    assert tok["access_token"] == "at-2"


@pytest.mark.asyncio
async def test_token_endpoint_erro_levanta(oauth_cfg):
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_grant"})

    async with _mock_client(handler) as c:
        with pytest.raises(gc.GoogleCalendarError):
            await gc.exchange_code("bad", client=c)


# ─── Eventos do Calendar ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insert_event(oauth_cfg):
    captured = {}

    def handler(request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "evt-1", "etag": '"etag-1"', "status": "confirmed"})

    event = {"summary": "Corte - Cliente E2E", "start": {"dateTime": "2026-12-30T14:00:00-03:00"}}
    async with _mock_client(handler) as c:
        res = await gc.insert_event("at-1", "primary", event, client=c)

    assert res["id"] == "evt-1"
    assert captured["method"] == "POST"
    assert captured["path"] == "/calendar/v3/calendars/primary/events"
    assert captured["auth"] == "Bearer at-1"


@pytest.mark.asyncio
async def test_update_event(oauth_cfg):
    def handler(request):
        assert request.method == "PATCH"
        assert request.url.path == "/calendar/v3/calendars/primary/events/evt-1"
        return httpx.Response(200, json={"id": "evt-1", "etag": '"etag-2"'})

    async with _mock_client(handler) as c:
        res = await gc.update_event("at-1", "primary", "evt-1", {"summary": "x"}, client=c)
    assert res["etag"] == '"etag-2"'


@pytest.mark.asyncio
async def test_delete_event_204(oauth_cfg):
    def handler(request):
        assert request.method == "DELETE"
        return httpx.Response(204)

    async with _mock_client(handler) as c:
        res = await gc.delete_event("at-1", "primary", "evt-1", client=c)
    assert res is None


@pytest.mark.asyncio
async def test_calendar_request_erro_levanta(oauth_cfg):
    def handler(request):
        return httpx.Response(403, json={"error": "forbidden"})

    async with _mock_client(handler) as c:
        with pytest.raises(gc.GoogleCalendarError):
            await gc.insert_event("at-1", "primary", {}, client=c)


@pytest.mark.asyncio
async def test_calendar_id_e_encodado_na_url(oauth_cfg):
    captured = {}

    def handler(request):
        captured["raw"] = request.url.raw_path.decode()
        return httpx.Response(200, json={"id": "e"})

    async with _mock_client(handler) as c:
        await gc.insert_event("at", "barbearia@gmail.com", {}, client=c)
    assert "barbearia%40gmail.com" in captured["raw"]
    assert "barbearia@gmail.com" not in captured["raw"]
