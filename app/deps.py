# file: app/deps.py
"""Dependências de request: autenticação e sessão com tenant aplicado (RLS)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import AsyncSessionLocal, set_current_org
from app.schemas.auth import TokenData
from models import User

bearer_scheme = HTTPBearer(auto_error=True)


def get_token_data(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> TokenData:
    """Decodifica o Bearer token. Não toca no banco."""
    try:
        payload = decode_access_token(creds.credentials)
        return TokenData(
            user_id=int(payload["sub"]),
            organization_id=int(payload["org"]),
        )
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_tenant_db(
    token: Annotated[TokenData, Depends(get_token_data)],
) -> AsyncIterator[AsyncSession]:
    """Sessão transacional com `app.current_org_id` definido a partir do token.

    Toda query feita com esta sessão é filtrada pela RLS para a org do usuário.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, token.organization_id)
            yield session


async def get_bot_db(
    x_bot_token: Annotated[Optional[str], Header(alias="X-Bot-Token")] = None,
) -> AsyncIterator[AsyncSession]:
    """Sessão para o chatbot: autentica via X-Bot-Token header."""
    if not settings.bot_api_key or x_bot_token != settings.bot_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bot token inválido ou ausente",
        )
    if not settings.bot_organization_id or not settings.bot_unit_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot não configurado (BOT_ORGANIZATION_ID / BOT_UNIT_ID ausentes)",
        )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, settings.bot_organization_id)
            yield session


async def get_current_user(
    token: Annotated[TokenData, Depends(get_token_data)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> User:
    """Carrega o usuário do token SOB RLS.

    Um usuário de outra organização simplesmente não é visível → 401.
    """
    user = (
        await db.execute(select(User).where(User.id == token.user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado no tenant atual",
        )
    return user
