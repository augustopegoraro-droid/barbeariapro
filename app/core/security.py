# file: app/core/security.py
"""Primitivas de segurança: hash de senha (bcrypt) e JWT (python-jose)."""

from __future__ import annotations

import hmac
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


def create_access_token(*, user_id: int, organization_id: int) -> str:
    """Emite um JWT contendo user_id (sub) e organization_id (org)."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": organization_id,
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
