# file: app/schemas/auth.py
"""Contratos de entrada/saída da autenticação."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    # organization_id define o tenant: a RLS escopa a busca do usuário a ele.
    organization_id: int = Field(..., gt=0, description="ID da organização (tenant).")
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    organization_id: int
    role: str
    must_change_password: bool = False


class TokenData(BaseModel):
    """Payload útil extraído do JWT."""

    user_id: int
    organization_id: int
    jti: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class SessionOut(BaseModel):
    id: int
    # Preenchidos só na listagem administrativa (/admin/security/sessions) —
    # o self-service (/auth/me/sessions) já sabe de quem é (é sempre o chamador).
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    device_label: Optional[str] = None
    user_agent: Optional[str] = None
    os: Optional[str] = None
    browser: Optional[str] = None
    ip: Optional[str] = None
    created_at: datetime
    last_seen_at: datetime
    is_current: bool


class AdminResetPasswordResponse(BaseModel):
    """Senha temporária devolvida UMA ÚNICA VEZ — repasse ao usuário é manual
    (fora do sistema; não há provedor de e-mail no stack, ver D-68)."""

    temporary_password: str


class AdminUserOut(BaseModel):
    """Usuário da org para a tela de gestão (`/admin/security/users`)."""

    id: int
    email: EmailStr
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime


class TenantResponse(BaseModel):
    """Resolução pública subdomínio → org (pré-login). Sem dados sensíveis."""

    organization_id: int
    name: str


class MeResponse(BaseModel):
    user_id: int
    organization_id: int
    email: EmailStr
    is_active: bool
    role: str
    must_change_password: bool = False
    # Prova de isolamento: sob RLS deve sempre ser 1 (apenas a própria org).
    organizations_visible: int


class MePermissionsResponse(BaseModel):
    """Permissões efetivas do usuário — consumidas pelo frontend só para UX
    (esconder menus/botões). NÃO é barreira: o backend reforça tudo."""

    user_id: int
    organization_id: int
    role: str
    permissions: list[str]
