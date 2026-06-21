# file: app/services/google_calendar.py
"""Cliente da API do Google Calendar + OAuth2 (núcleo da Fase 2).

Wrapper async (httpx) sobre os endpoints REST do Google:
  - OAuth2: montar URL de consentimento, trocar `code` por tokens, refresh.
  - Eventos: insert / update / delete em um calendário.

Sem efeito colateral no import. Toda função de rede aceita um
`httpx.AsyncClient` opcional (`client=`) para permitir testes com
`httpx.MockTransport` — nenhuma chamada real é feita nos testes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

import httpx

from app.core.config import settings

_logger = logging.getLogger(__name__)

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
_TIMEOUT = 15.0


class GoogleCalendarError(RuntimeError):
    """Falha em chamada à API do Google (OAuth ou Calendar)."""


def _require_oauth_config() -> None:
    if not (settings.google_client_id and settings.google_client_secret):
        raise GoogleCalendarError(
            "Google OAuth não configurado (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)."
        )


def build_authorization_url(state: str, *, scopes: Optional[str] = None) -> str:
    """URL de consentimento OAuth2. `state` carrega contexto (ex.: org_id assinado).

    `access_type=offline` + `prompt=consent` garantem o refresh_token mesmo em
    reautorização.
    """
    if not (settings.google_client_id and settings.google_redirect_uri):
        raise GoogleCalendarError(
            "Google OAuth não configurado (GOOGLE_CLIENT_ID / GOOGLE_REDIRECT_URI)."
        )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": scopes or settings.google_calendar_scopes,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URI}?{urlencode(params)}"


async def _post_token(data: Dict[str, str], client: Optional[httpx.AsyncClient]) -> Dict[str, Any]:
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        resp = await client.post(GOOGLE_TOKEN_URI, data=data)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise GoogleCalendarError(
            f"token endpoint -> {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except httpx.HTTPError as exc:
        raise GoogleCalendarError(f"falha de rede no token endpoint: {exc}") from exc
    finally:
        if owns:
            await client.aclose()


async def exchange_code(code: str, *, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Troca o authorization `code` por access_token + refresh_token."""
    _require_oauth_config()
    return await _post_token(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        client,
    )


async def refresh_access_token(
    refresh_token: str, *, client: Optional[httpx.AsyncClient] = None
) -> Dict[str, Any]:
    """Obtém um novo access_token a partir do refresh_token."""
    _require_oauth_config()
    return await _post_token(
        {
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        },
        client,
    )


async def _calendar_request(
    method: str,
    path: str,
    access_token: str,
    *,
    json: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[Dict[str, Any]]:
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    url = f"{CALENDAR_API_BASE}{path}"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = await client.request(method, url, headers=headers, json=json)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise GoogleCalendarError(
            f"calendar {method} {path} -> {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except httpx.HTTPError as exc:
        raise GoogleCalendarError(f"falha de rede em {method} {path}: {exc}") from exc
    finally:
        if owns:
            await client.aclose()


async def insert_event(
    access_token: str,
    calendar_id: str,
    event: Dict[str, Any],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Cria um evento. Retorna o recurso do evento (com `id`, `etag`)."""
    cal = quote(calendar_id, safe="")
    return await _calendar_request(
        "POST", f"/calendars/{cal}/events", access_token, json=event, client=client
    )


async def update_event(
    access_token: str,
    calendar_id: str,
    event_id: str,
    event: Dict[str, Any],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Atualiza (PATCH parcial) um evento existente."""
    cal = quote(calendar_id, safe="")
    eid = quote(event_id, safe="")
    return await _calendar_request(
        "PATCH", f"/calendars/{cal}/events/{eid}", access_token, json=event, client=client
    )


async def delete_event(
    access_token: str,
    calendar_id: str,
    event_id: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """Remove um evento. Idempotente do ponto de vista do chamador."""
    cal = quote(calendar_id, safe="")
    eid = quote(event_id, safe="")
    await _calendar_request(
        "DELETE", f"/calendars/{cal}/events/{eid}", access_token, client=client
    )
