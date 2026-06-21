# file: app/api/integracoes.py
"""Endpoints de integração OAuth — Fase 2 (Google Calendar).

Fluxo:
  1. GET /integracoes/google/calendar/authorize  (requer JWT owner/manager)
     → gera state JWT assinado e redireciona para o consentimento Google.
  2. GET /integracoes/google/calendar/callback   (público — redirect do Google)
     → verifica state, troca code por tokens, cifra e persiste em
       integration_accounts.

Segurança do state: JWT assinado com settings.secret_key, TTL de 5 min,
contendo org_id. Impede CSRF e carrega contexto de tenant sem sessão server-side.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import TokenCryptoError, encrypt_token
from app.db.session import AsyncSessionLocal, set_current_org
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.services import google_calendar as gc
from models import User
from models.enums import IntegrationProvider, IntegrationStatus
from models.integration import IntegrationAccount

router = APIRouter(prefix="/integracoes", tags=["integracoes"])

_STATE_ALG = "HS256"
_STATE_TTL_SECONDS = 300  # 5 minutos


# ─── helpers de state ─────────────────────────────────────────────────────────

def _build_state(org_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(org_id),
        "iat": now,
        "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_STATE_ALG)


def _verify_state(state: str) -> int:
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[_STATE_ALG])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state OAuth inválido ou expirado — inicie o fluxo novamente",
        )


# ─── endpoints ────────────────────────────────────────────────────────────────

@router.get("/google/calendar/authorize", summary="Inicia o fluxo OAuth2 do Google Calendar")
async def authorize_google_calendar(
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RedirectResponse:
    """Redireciona o usuário para a tela de consentimento do Google.

    Apenas owner e manager podem conectar o Google Calendar da organização.
    """
    role = await resolve_current_role(db, current_user)
    if role not in ("owner", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas owner/manager pode conectar o Google Calendar",
        )

    state = _build_state(current_user.organization_id)
    try:
        url = gc.build_authorization_url(state=state)
    except gc.GoogleCalendarError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    return RedirectResponse(url=url, status_code=302)


@router.get("/google/calendar/callback", summary="Callback OAuth2 do Google (redirect automático)")
async def google_calendar_callback(
    code: Annotated[Optional[str], Query()] = None,
    state: Annotated[Optional[str], Query()] = None,
    error: Annotated[Optional[str], Query()] = None,
) -> JSONResponse:
    """Recebe o authorization code do Google, troca por tokens e persiste.

    Endpoint público (sem JWT) — a autenticação do tenant vem do `state`
    assinado gerado em /authorize.
    """
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google recusou a autorização: {error}",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parâmetros 'code' e 'state' são obrigatórios",
        )

    org_id = _verify_state(state)

    try:
        tokens = await gc.exchange_code(code)
    except gc.GoogleCalendarError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google não retornou access_token",
        )

    try:
        token_enc = encrypt_token(access_token)
        refresh_enc = encrypt_token(refresh_token) if refresh_token else None
    except TokenCryptoError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao cifrar tokens: {exc}",
        )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            existing = (
                await session.execute(
                    select(IntegrationAccount)
                    .where(
                        IntegrationAccount.organization_id == org_id,
                        IntegrationAccount.provider == IntegrationProvider.google_calendar,
                    )
                    .order_by(IntegrationAccount.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if existing:
                existing.token_encrypted = token_enc
                existing.refresh_token_encrypted = refresh_enc
                existing.status = IntegrationStatus.active
            else:
                session.add(
                    IntegrationAccount(
                        organization_id=org_id,
                        provider=IntegrationProvider.google_calendar,
                        token_encrypted=token_enc,
                        refresh_token_encrypted=refresh_enc,
                        status=IntegrationStatus.active,
                    )
                )

    return JSONResponse(
        content={"status": "ok", "message": "Google Calendar conectado com sucesso"},
        status_code=200,
    )
