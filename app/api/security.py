# file: app/api/security.py
"""Área "Segurança" (gestor): sessões/dispositivos de qualquer usuário da org
e reset administrativo de senha (D-68, Fase 3).

Complementa o self-service em `/auth/me/sessions` (app/api/auth.py) — aqui é
o gestor agindo sobre OUTRO usuário (ex.: funcionário desligado), por isso
exige as permissões `security.sessions.*`/`security.users.manage` (já no
catálogo, `app/core/permissions.py:97-99`).
"""

from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.core.rate_limit import limiter
from app.core.security import hash_password, secrets_match
from app.db.redis import get_redis
from app.core.config import settings
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.schemas.audit import AuditLogListOut, AuditLogOut
from app.schemas.auth import AdminResetPasswordResponse, AdminUserOut, SessionOut
from app.schemas.security_dashboard import SecurityDashboardOut
from app.services.audit import purge_expired, record_event
from app.services.security_dashboard import dashboard_summary
from models import AuditLog, User, UserSession

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
    request: Request,
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
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="security.sessions.revoke",
        resource_type="session",
        resource_id=session_id,
        after={"target_user_id": row.user_id},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


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

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="security.users.reset_password",
        resource_type="user",
        resource_id=user_id,
        reason="Reset administrativo de senha",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return AdminResetPasswordResponse(temporary_password=temp_password)


# ─── Painel de segurança (Fase 5) ───────────────────────────────────────────

@router.get("/dashboard", response_model=SecurityDashboardOut)
async def security_dashboard(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    days: int = Query(30, ge=1, le=90),
) -> SecurityDashboardOut:
    """Cards + série diária + alerta de anomalia (ARQUITETURA_ALVO.md §3, Fase 5).

    Gated por `security.audit.view` — o painel é construído em cima de
    `audit_logs`, mesma fonte/permissão da tela de Auditoria (Fase 4); não
    introduz permissão nova para não exigir re-sync do catálogo."""
    await require_permission(db, current_user, "security.audit.view")
    data = await dashboard_summary(db, current_user.organization_id, days=days)
    return SecurityDashboardOut(**data)


# ─── Auditoria (Fase 4) ─────────────────────────────────────────────────────

def _audit_filters(
    *,
    actor_user_id: Optional[int],
    action: Optional[str],
    resource_type: Optional[str],
    result: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> list:
    conditions = []
    if actor_user_id is not None:
        conditions.append(AuditLog.actor_user_id == actor_user_id)
    if action:
        conditions.append(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if result in ("allow", "deny"):
        conditions.append(AuditLog.result == result)
    if date_from is not None:
        conditions.append(AuditLog.created_at >= date_from)
    if date_to is not None:
        conditions.append(AuditLog.created_at <= date_to)
    return conditions


@router.get("/audit", response_model=AuditLogListOut)
async def list_audit_logs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    actor_user_id: Optional[int] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    result: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AuditLogListOut:
    """Timeline filtrável/pesquisável (ARQUITETURA_ALVO.md §1.7/§1.12)."""
    await require_permission(db, current_user, "security.audit.view")
    conditions = _audit_filters(
        actor_user_id=actor_user_id, action=action, resource_type=resource_type,
        result=result, date_from=date_from, date_to=date_to,
    )
    total = (
        await db.execute(select(func.count(AuditLog.id)).where(*conditions))
    ).scalar_one()
    rows = (
        await db.execute(
            select(AuditLog, User.email)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(*conditions)
            .order_by(AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return AuditLogListOut(
        items=[
            AuditLogOut(
                id=r.id,
                actor_user_id=r.actor_user_id,
                actor_email=email,
                actor_kind=r.actor_kind,
                action=r.action,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                before=r.before,
                after=r.after,
                result=r.result,
                reason=r.reason,
                ip=r.ip,
                user_agent=r.user_agent,
                created_at=r.created_at,
            )
            for r, email in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/audit/export.csv")
async def export_audit_logs_csv(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    actor_user_id: Optional[int] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    result: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Response:
    """Exportação da auditoria — controlada por permissão própria e ela mesma
    auditada (§1.7: "exportação também controlada... e ela própria auditada")."""
    await require_permission(db, current_user, "security.audit.export")
    conditions = _audit_filters(
        actor_user_id=actor_user_id, action=action, resource_type=resource_type,
        result=result, date_from=date_from, date_to=date_to,
    )
    rows = (
        await db.execute(
            select(AuditLog, User.email)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(*conditions)
            .order_by(AuditLog.id.desc())
            .limit(5000)
        )
    ).all()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Data/hora", "Ator", "Ação", "Recurso", "Resultado", "Motivo", "IP"])
    for r, email in rows:
        writer.writerow([
            r.created_at.isoformat(),
            email or r.actor_kind,
            r.action,
            f"{r.resource_type or ''}#{r.resource_id or ''}".strip("#"),
            r.result,
            r.reason or "",
            r.ip or "",
        ])

    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="security.audit.export",
        resource_type="audit_logs",
        reason=f"{len(rows)} linha(s)",
    )
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="auditoria.csv"'},
    )


# ─── cron interno (n8n) — purga por retenção (X-Bot-Token) ──────────────────

internal_router = APIRouter(prefix="/internal/audit", tags=["audit-internal"])


@internal_router.post("/purge")
async def purge_audit_logs(
    x_bot_token: Annotated[Optional[str], Header(alias="X-Bot-Token")] = None,
) -> dict:
    """Apaga linhas além da retenção configurada por org (`app_audit_purge_expired`,
    SECURITY DEFINER — roda por cima de todas as orgs numa só chamada)."""
    if not settings.bot_api_key or not secrets_match(x_bot_token or "", settings.bot_api_key):
        raise HTTPException(status_code=401, detail="Token inválido.")
    deleted = await purge_expired()
    return {"deleted": deleted}
