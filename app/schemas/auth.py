# file: app/schemas/auth.py
"""Contratos de entrada/saída da autenticação."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    # organization_id define o tenant: a RLS escopa a busca do usuário a ele.
    organization_id: int = Field(..., gt=0, description="ID da organização (tenant).")
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Payload útil extraído do JWT."""

    user_id: int
    organization_id: int


class MeResponse(BaseModel):
    user_id: int
    organization_id: int
    email: EmailStr
    is_active: bool
    # Prova de isolamento: sob RLS deve sempre ser 1 (apenas a própria org).
    organizations_visible: int
