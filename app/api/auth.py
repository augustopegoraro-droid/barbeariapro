# file: app/api/auth.py
"""Rotas de autenticação: login (emite JWT) e /me (protegida, prova RLS)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.db.session import get_db, set_current_org
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse
from models import Organization, User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    # Define o tenant ANTES de consultar; a RLS restringe `users` à organização.
    await set_current_org(db, body.organization_id)
    user = (
        await db.execute(select(User).where(User.email == str(body.email)))
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
        )
    role = await resolve_current_role(db, user)
    token = create_access_token(user_id=user.id, organization_id=user.organization_id)
    return TokenResponse(
        access_token=token,
        organization_id=user.organization_id,
        role=role,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MeResponse:
    # Sob RLS, só a própria organização é visível → count deve ser 1.
    visible = (
        await db.execute(select(func.count()).select_from(Organization))
    ).scalar_one()
    me_role = await resolve_current_role(db, current_user)
    return MeResponse(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        email=current_user.email,
        is_active=current_user.is_active,
        role=me_role,
        organizations_visible=int(visible),
    )
