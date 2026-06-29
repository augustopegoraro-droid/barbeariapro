# file: app/deps.py
"""Dependências de request: autenticação e sessão com tenant aplicado (RLS)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rbac import resolve_role, resolve_role_with_barber
from app.core.security import decode_access_token, secrets_match
from app.db.session import AsyncSessionLocal, set_current_org
from app.schemas.auth import TokenData
from app.services.tenant import org_id_by_wa_instance
from models import Unit, User, UserUnit

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
    request: Request,
    x_bot_token: Annotated[Optional[str], Header(alias="X-Bot-Token")] = None,
    x_instance: Annotated[Optional[str], Header(alias="X-Instance")] = None,
) -> AsyncIterator[AsyncSession]:
    """Sessão para o chatbot: autentica via X-Bot-Token header.

    Multi-tenant: a org/unidade vêm da instância WhatsApp (header `X-Instance`,
    enviado pelo n8n). Sem o header — ou instância sem mapeamento — cai no
    comportamento legado single-tenant via `settings.bot_organization_id` /
    `bot_unit_id`. O par resolvido fica em `request.state` para os endpoints
    consumirem via `get_bot_org_id` / `get_bot_unit_id` (em vez de ler `settings`).
    """
    if not secrets_match(x_bot_token, settings.bot_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bot token inválido ou ausente",
        )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Resolve a org pela instância (sem tenant: a função SQL ignora a RLS).
            org_id = await org_id_by_wa_instance(session, x_instance or "")
            unit_id: Optional[int] = None
            if org_id is None:
                org_id = settings.bot_organization_id or None
                unit_id = settings.bot_unit_id or None
            if not org_id:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Bot não configurado (sem instância mapeada nem BOT_ORGANIZATION_ID)",
                )
            await set_current_org(session, org_id)
            if unit_id is None:
                # Org veio da instância: usa a unidade padrão (menor id, não excluída).
                unit_id = (
                    await session.execute(
                        select(Unit.id)
                        .where(Unit.deleted_at.is_(None))
                        .order_by(Unit.id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
            request.state.bot_org_id = org_id
            request.state.bot_unit_id = unit_id
            yield session


async def get_bot_org_id(
    request: Request,
    _db: Annotated[AsyncSession, Depends(get_bot_db)],
) -> int:
    """org_id resolvido pelo `get_bot_db` (instância → org, com fallback a settings).

    Depende de `get_bot_db` (cacheado no request) só para garantir a ordem de
    resolução; lê o valor de `request.state`."""
    return request.state.bot_org_id


async def get_bot_unit_id(
    request: Request,
    _db: Annotated[AsyncSession, Depends(get_bot_db)],
) -> Optional[int]:
    """unit_id resolvido pelo `get_bot_db` (unidade da instância, ou settings)."""
    return request.state.bot_unit_id


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


async def _org_scoped_unit_links(db: AsyncSession, user: User) -> list[UserUnit]:
    """Vínculos do usuário com unidades da SUA organização.

    `user_units` não tem RLS própria (é tabela-filha). O join com `units`
    — que tem RLS — garante o escopo de tenant: sem isto a query veria
    vínculos de outras organizações e a role efetiva poderia ser elevada
    entre tenants.
    """
    rows = (
        await db.execute(
            select(UserUnit)
            .join(Unit, Unit.id == UserUnit.unit_id)
            .where(UserUnit.user_id == user.id)
        )
    ).scalars().all()
    return list(rows)


async def resolve_current_role(db: AsyncSession, user: User) -> str:
    """Role efetiva (maior prioridade) do usuário na org atual."""
    return resolve_role(await _org_scoped_unit_links(db, user))


async def resolve_current_role_with_barber(
    db: AsyncSession, user: User
) -> tuple[str, Optional[int]]:
    """(role, barber_id) escopado à org atual; barber_id só quando role='barber'."""
    return resolve_role_with_barber(await _org_scoped_unit_links(db, user))
