# file: app/api/auth.py
"""Rotas de autenticação: login, refresh/logout, troca de senha, sessões, /me.

D-68 (Fase 3): access token curto (15 min) + refresh token rotativo com
detecção de reuso (tabela `sessions`, Postgres — fonte de verdade); Redis só
guarda dado efêmero (contadores de lockout, denylist curta de `jti`). Ver
`app/core/security.py` (jti/refresh) e `app/db/redis.py`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import user_agents
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import AuthContext, get_auth_context
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.db.redis import get_redis
from app.db.session import get_db, set_current_org
from app.deps import get_current_user, get_tenant_db, get_token_data, resolve_current_role
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    MePermissionsResponse,
    MeResponse,
    RefreshRequest,
    SessionOut,
    TenantResponse,
    TokenData,
    TokenResponse,
)
from app.services.tenant import org_id_by_refresh_token_hash, org_id_by_subdomain
from models import Organization, User, UserSession

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _is_locked(key: str) -> bool:
    try:
        redis = get_redis()
        value = await redis.get(key)
    except Exception:
        # Redis indisponível: fail-open no lockout — a senha continua sendo a
        # barreira real; não derruba o login por causa de um serviço auxiliar.
        return False
    return value is not None and int(value) >= settings.login_max_attempts


async def _register_login_failure(*keys: str) -> None:
    try:
        redis = get_redis()
        for key in keys:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, settings.login_lockout_window_seconds)
            elif count == settings.login_max_attempts:
                await redis.expire(key, settings.login_lockout_duration_seconds)
    except Exception:
        pass


async def _clear_login_failures(*keys: str) -> None:
    try:
        redis = get_redis()
        for key in keys:
            await redis.delete(key)
    except Exception:
        pass


async def _denylist_jti(jti: str) -> None:
    """Kill imediato de um access token no logout (defesa em profundidade —
    ele já expira em `access_token_expire_minutes` de qualquer forma)."""
    try:
        redis = get_redis()
        await redis.setex(f"denylist:{jti}", settings.access_token_expire_minutes * 60, "1")
    except Exception:
        pass


async def _issue_session(
    db: AsyncSession, request: Request, user: User, role: str
) -> TokenResponse:
    """Cria a `Session` (dispositivo) + emite access/refresh do login."""
    jti = uuid.uuid4().hex
    access_token = create_access_token(user_id=user.id, organization_id=user.organization_id, jti=jti)
    raw_refresh, refresh_hash = generate_refresh_token()
    ua_string = (request.headers.get("user-agent") or "")[:500]
    parsed = user_agents.parse(ua_string) if ua_string else None
    now = datetime.now(timezone.utc)
    session_row = UserSession(
        organization_id=user.organization_id,
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        jti_current=jti,
        user_agent=ua_string or None,
        os=parsed.get_os() if parsed else None,
        browser=parsed.get_browser() if parsed else None,
        ip=_client_ip(request),
        refresh_expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session_row)
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        organization_id=user.organization_id,
        role=role,
        must_change_password=user.must_change_password,
    )


@router.get("/tenant", response_model=TenantResponse)
@limiter.limit("20/minute")
async def resolve_tenant(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantResponse:
    """Resolve o tenant pelo subdomínio (pré-login). Público: o frontend chama
    antes de autenticar para descobrir o `organization_id` do host, substituindo
    `NEXT_PUBLIC_ORG_ID`. Devolve só id + nome (sem dados sensíveis)."""
    org_id = await org_id_by_subdomain(db, subdomain)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant não encontrado para o subdomínio informado.",
        )
    # org_id veio de função SECURITY DEFINER (ignora RLS); agora escopa a sessão
    # ao tenant para ler o nome sob RLS normal. scalar_one_or_none + 404 evita 500
    # numa corrida (org soft-deletada entre a resolução e este SELECT).
    await set_current_org(db, org_id)
    name = (
        await db.execute(select(Organization.name).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if name is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant não encontrado para o subdomínio informado.",
        )
    return TenantResponse(organization_id=org_id, name=name)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    ip = _client_ip(request)
    email_key = str(body.email).strip().lower()
    ip_key = f"login_fail:ip:{ip}"
    combo_key = f"login_fail:combo:{ip}:{email_key}"
    if await _is_locked(ip_key) or await _is_locked(combo_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas. Tente novamente em alguns minutos.",
        )

    # Define o tenant ANTES de consultar; a RLS restringe `users` à organização.
    await set_current_org(db, body.organization_id)
    org = (
        await db.execute(
            select(Organization).where(Organization.id == body.organization_id)
        )
    ).scalar_one_or_none()
    user = (
        await db.execute(select(User).where(User.email == str(body.email)))
    ).scalar_one_or_none()

    # V13 (anti-enumeração): roda o bcrypt SEMPRE, com o hash real ou um dummy
    # fixo — o custo (dominante em relação às queries) fica uniforme entre
    # "usuário não existe", "senha errada" e "org suspensa", que devolvem a
    # MESMA mensagem genérica (a suspensão deixou de ter um 403 distinto).
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_ok = verify_password(body.password, password_hash)
    account_ok = user is not None and user.is_active
    org_ok = org is not None and org.deleted_at is None
    if not (password_ok and account_ok and org_ok):
        await _register_login_failure(ip_key, combo_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
        )

    await _clear_login_failures(ip_key, combo_key)
    assert user is not None  # narrows p/ o type checker (já garantido por account_ok)
    role = await resolve_current_role(db, user)
    return await _issue_session(db, request, user, role)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Rotaciona o refresh token. Reuso de um token já rotacionado revoga a
    sessão inteira (indício de token roubado) — ver docstring do módulo.

    Detecção de reuso cobre UMA geração (`prev_refresh_token_hash`, sobrescrito
    a cada rotação) — cobre o caso real de ataque (corrida entre o dono
    legítimo e quem roubou o token, ambos com o mesmo token válido por vez).
    Um token roubado e reapresentado 2+ rotações depois já falha por conta
    própria ("inválido", sem casar com atual nem anterior) — não concede
    acesso — só não dispara a revogação proativa+alerta da sessão inteira
    nesse caso mais raro. Histórico completo exigiria uma tabela à parte;
    fora de escopo desta fase."""
    token_hash = hash_refresh_token(body.refresh_token)
    org_id = await org_id_by_refresh_token_hash(db, token_hash)
    if org_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")
    await set_current_org(db, org_id)

    session_row = (
        await db.execute(
            select(UserSession).where(
                UserSession.organization_id == org_id,
                (UserSession.refresh_token_hash == token_hash)
                | (UserSession.prev_refresh_token_hash == token_hash),
            )
        )
    ).scalar_one_or_none()
    if session_row is None or session_row.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

    # `get_db` só faz commit se o handler retornar normalmente — como estes 3
    # ramos revogam a sessão e IMEDIATAMENTE levantam HTTPException, a exceção
    # propagando por dentro do `async with session.begin()` faria ROLLBACK e a
    # revogação nunca seria persistida. `db.commit()` explícito antes do raise
    # (mesmo padrão já usado em wa_webhook.py/chatwoot.py) garante que ela grave.
    now = datetime.now(timezone.utc)
    if session_row.refresh_expires_at < now:
        session_row.revoked_at = now
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expirado")

    if session_row.prev_refresh_token_hash == token_hash:
        session_row.revoked_at = now
        logger.warning(
            "auth.refresh_reuse_detected session_id=%s user_id=%s org_id=%s",
            session_row.id, session_row.user_id, org_id,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão revogada (reuso de refresh token detectado)",
        )

    user = (
        await db.execute(select(User).where(User.id == session_row.user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        session_row.revoked_at = now
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inválido")

    role = await resolve_current_role(db, user)
    new_jti = uuid.uuid4().hex
    access_token = create_access_token(user_id=user.id, organization_id=user.organization_id, jti=new_jti)
    raw_refresh, refresh_hash = generate_refresh_token()

    session_row.prev_refresh_token_hash = session_row.refresh_token_hash
    session_row.refresh_token_hash = refresh_hash
    session_row.jti_current = new_jti
    session_row.last_seen_at = now
    session_row.refresh_expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    session_row.ip = _client_ip(request)

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        organization_id=user.organization_id,
        role=role,
        must_change_password=user.must_change_password,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoga a sessão do refresh token informado. Idempotente: token já
    revogado/inexistente não é erro (nunca vaza esse estado ao chamador)."""
    token_hash = hash_refresh_token(body.refresh_token)
    org_id = await org_id_by_refresh_token_hash(db, token_hash)
    if org_id is None:
        return
    await set_current_org(db, org_id)
    session_row = (
        await db.execute(
            select(UserSession).where(
                UserSession.organization_id == org_id,
                (UserSession.refresh_token_hash == token_hash)
                | (UserSession.prev_refresh_token_hash == token_hash),
            )
        )
    ).scalar_one_or_none()
    if session_row is None:
        return
    session_row.revoked_at = datetime.now(timezone.utc)
    await _denylist_jti(session_row.jti_current)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    token: Annotated[TokenData, Depends(get_token_data)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    """Troca a própria senha. Revoga as OUTRAS sessões (mantém a atual) —
    rotacionar a senha deve encerrar qualquer dispositivo que a tenha roubado."""
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Senha atual incorreta")
    current_user.password_hash = hash_password(body.new_password)
    current_user.must_change_password = False

    now = datetime.now(timezone.utc)
    other_sessions = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == current_user.id,
                UserSession.revoked_at.is_(None),
                UserSession.jti_current != token.jti,
            )
        )
    ).scalars().all()
    for row in other_sessions:
        row.revoked_at = now
        await _denylist_jti(row.jti_current)


@router.get("/me/sessions", response_model=list[SessionOut])
async def list_my_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    token: Annotated[TokenData, Depends(get_token_data)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[SessionOut]:
    """Dispositivos/sessões ativos do usuário logado (self-service)."""
    rows = (
        await db.execute(
            select(UserSession)
            .where(UserSession.user_id == current_user.id, UserSession.revoked_at.is_(None))
            .order_by(UserSession.last_seen_at.desc())
        )
    ).scalars().all()
    return [
        SessionOut(
            id=r.id,
            device_label=r.device_label,
            user_agent=r.user_agent,
            os=r.os,
            browser=r.browser,
            ip=r.ip,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            is_current=(r.jti_current == token.jti),
        )
        for r in rows
    ]


@router.post("/me/sessions/{session_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    """Revoga um dos PRÓPRIOS dispositivos — sem permissão extra, é sobre o
    próprio acesso. Revogar sessões de outros usuários é `/admin/security/*`."""
    row = (
        await db.execute(
            select(UserSession).where(
                UserSession.id == session_id, UserSession.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessão não encontrada")
    row.revoked_at = datetime.now(timezone.utc)
    row.revoked_by = current_user.id
    await _denylist_jti(row.jti_current)


@router.post("/me/sessions/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_my_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    token: Annotated[TokenData, Depends(get_token_data)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    """"Sair de todos os outros dispositivos" — preserva a sessão atual (o
    próprio dispositivo de onde o pedido partiu)."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == current_user.id,
                UserSession.revoked_at.is_(None),
                UserSession.jti_current != token.jti,
            )
        )
    ).scalars().all()
    for row in rows:
        row.revoked_at = now
        row.revoked_by = current_user.id
        await _denylist_jti(row.jti_current)


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
        must_change_password=current_user.must_change_password,
        organizations_visible=int(visible),
    )


@router.get("/me/permissions", response_model=MePermissionsResponse)
async def my_permissions(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MePermissionsResponse:
    """Permissões efetivas do usuário logado (para renderização condicional no
    frontend). Apenas UX — toda autorização é reforçada no backend."""
    role = await resolve_current_role(db, ctx.user)
    return MePermissionsResponse(
        user_id=ctx.user.id,
        organization_id=ctx.user.organization_id,
        role=role,
        permissions=sorted(ctx.permissions),
    )
