# file: app/schemas/audit.py
"""Contratos da área "Auditoria" (`/admin/security/audit`, Fase 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AuditLogOut(BaseModel):
    id: int
    actor_user_id: Optional[int] = None
    actor_email: Optional[str] = None
    actor_kind: str
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    result: str
    reason: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


class AuditLogListOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int


class AuditChainOut(BaseModel):
    """Resultado da verificação da cadeia de hash (D-86)."""

    checked: int
    ok: bool
    # "link" = linha removida/inserida no meio; "payload" = linha editada.
    kind: Optional[str] = None
    broken_at_id: Optional[int] = None
    broken_at: Optional[datetime] = None


class RetentionOut(BaseModel):
    audit_retention_months: int


class RetentionUpdateIn(BaseModel):
    # Teto de 10 anos: acima disso o "prazo" deixa de ser retenção e vira
    # guarda indefinida, que é exatamente o que a LGPD quer evitar.
    audit_retention_months: int = Field(ge=1, le=120)
