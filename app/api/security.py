# file: app/api/security.py
"""Área "Segurança" (gestor): sessões/dispositivos de qualquer usuário da org
e reset administrativo de senha (D-68, Fase 3).

Complementa o self-service em `/auth/me/sessions` (app/api/auth.py) — aqui é
o gestor agindo sobre OUTRO usuário (ex.: funcionário desligado), por isso
exige as permissões `security.sessions.*`/`security.users.manage` (já no
catálogo, `app/core/permissions.py:97-99`).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.db.redis import get_redis
from app.core.config import settings
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.schemas.auth import AdminResetPasswordResponse, AdminUserOut, SessionOut
from models import User, UserSession

router = APIRouter(prefix="/admin/security", tags=["security"])


async def _denylist_jti(jti: str) -> None:
    try:
        redis = get_redis()
        await redis.setex(f"denylist:{jti}", settings.access_token_expire_minutes * 60, "1")
    except Exception:
        pass


@router.get("/users", response_model=list[AdminUserOut])
async def list_org_users(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[AdminUserOut]:
    """Usuários da org (RLS já escopa) — base da tela de gestão de acesso."""
    await require_permission(db, current_user, "security.users.manage")
    rows = (
        await db.execute(
            select(User).where(User.deleted_at.is_(None)).order_by(User.email)
        )
    ).scalars().all()
    return [
        AdminUserOut(
            id=r.id,
            email=r.email,
            role=await resolve_current_role(db, r),
            is_active=r.is_active,
            must_change_password=r.must_change_password,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    user_id: Optional[int] = None,
) -> list[SessionOut]:
    """Sessões ativas da org (RLS já escopa) — opcionalmente filtradas por usuário."""
    await require_permission(db, current_user, "security.sessions.view")
    query = (
        select(UserSession, User.email)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.revoked_at.is_(None))
    )
    if user_id is not None:
        query = query.where(UserSession.user_id == user_id)
    rows = (
        await db.execute(query.order_by(UserSession.last_seen_at.desc()))
    ).all()
    return [
        SessionOut(
            id=r.id,
            user_id=r.user_id,
            user_email=email,
            device_label=r.device_label,
            user_agent=r.user_agent,
            os=r.os,
            browser=r.browser,
            ip=r.ip,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            is_current=False,
        )
        for r, email in rows
    ]


@router.post("/sessions/{session_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    await require_permission(db, current_user, "security.sessions.revoke")
    row = (
        await db.execute(select(UserSession).where(UserSession.id == session_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessão não encontrada")
    row.revoked_at = datetime.now(timezone.utc)
    row.revoked_by = current_user.id
    await _denylist_jti(row.jti_current)


@router.post("/users/{user_id}/reset-password", response_model=AdminResetPasswordResponse)
@limiter.limit("5/minute")
async def reset_user_password(
    request: Request,
    user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AdminResetPasswordResponse:
    """Gera uma senha temporária para outro usuário e revoga TODAS as sessões
    dele. Sem e-mail no stack (D-68, decisão registrada): o repasse ao usuário
    é manual, fora do sistema — a senha só aparece nesta resposta, uma vez."""
    await require_permission(db, current_user, "security.users.manage")
    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

    temp_password = secrets.token_urlsafe(12)
    target.password_hash = hash_password(temp_password)
    target.must_change_password = True

    now = datetime.now(timezone.utc)
    sessions = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == target.id, UserSession.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    for row in sessions:
        row.revoked_at = now
        row.revoked_by = current_user.id
        await _denylist_jti(row.jti_current)

    return AdminResetPasswordResponse(temporary_password=temp_password)
