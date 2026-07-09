# file: app/core/security.py
"""Primitivas de segurança: hash de senha (bcrypt) e JWT (python-jose)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import jwt

from app.core.config import settings


def secrets_match(provided: Optional[str], expected: str) -> bool:
    """Compara dois segredos em tempo constante (resistente a timing attack).

    Retorna False se o valor recebido for vazio/ausente. Use para validar
    tokens estáticos como X-Bot-Token e X-Webhook-Secret.
    """
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def hash_password(plain: str) -> str:
    """Gera o hash bcrypt de uma senha em texto puro."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Confere a senha contra o hash armazenado (users.password_hash)."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# Hash fixo (calculado 1x na importação) para rodar `verify_password` mesmo
# quando o usuário não existe — uniformiza o custo do bcrypt no /auth/login e
# fecha a enumeração por timing (V13). Nunca é a senha de ninguém.
DUMMY_PASSWORD_HASH = hash_password("d68-timing-uniform-dummy-not-a-real-password")


def create_access_token(*, user_id: int, organization_id: int, jti: Optional[str] = None) -> str:
    """Emite um JWT contendo user_id (sub), organization_id (org) e jti (D-68).

    `jti` identifica este access token para o denylist de logout (Redis, curto
    prazo — o token já expira em `access_token_expire_minutes`). Se não vier
    (compat com chamadores antigos), gera um novo — o `jti` só é rastreado por
    quem o gerou (login/refresh), que já o guarda em `sessions.jti_current`.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": organization_id,
        "jti": jti or uuid.uuid4().hex,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def generate_refresh_token() -> tuple[str, str]:
    """Gera um refresh token opaco de 256 bits: `(raw, hash)`.

    `raw` é devolvido uma única vez ao cliente; só `hash` (sha256, determinístico
    — não é senha, já tem entropia suficiente, precisa de lookup rápido por
    índice único) é persistido em `sessions.refresh_token_hash`.
    """
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    """Hash determinístico (sha256) de um refresh token — usado para lookup."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_impersonation_token(
    *, user_id: int, organization_id: int, admin_id: int, minutes: int = 30
) -> str:
    """JWT de TENANT emitido pela PLATAFORMA para suporte (superadmin M10).

    Mesmo shape do token de tenant (sub/org/jti — aceito por get_token_data sem
    mudanças) + claim `imp_by` (id do superadmin) para rastreabilidade, e
    expiração CURTA (default 30 min). O motivo fica no platform_audit_log,
    não no token. `jti` próprio (D-68): permite revogar uma impersonação via
    denylist mesmo sem uma `sessions` row (impersonação não passa por login).
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=max(5, min(minutes, 60)))
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": organization_id,
        "imp_by": admin_id,
        "jti": uuid.uuid4().hex,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_platform_token(*, admin_id: int) -> str:
    """Emite um JWT de PLATAFORMA (superadmin do SaaS).

    Distinto do token de tenant: carrega `typ="platform"` e **não** carrega `org`.
    Assim, o guard de tenant (`get_token_data`, que exige `org`) rejeita este token,
    e o guard de plataforma (que exige `typ="platform"`) rejeita os de tenant.
    Mesma chave/HS256.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(admin_id),
        "typ": "platform",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica e valida (assinatura + exp) o JWT. Lança JWTError se inválido."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
