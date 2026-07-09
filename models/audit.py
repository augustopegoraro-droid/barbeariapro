"""Auditoria do tenant (Fase 4, ARQUITETURA_ALVO.md §1.7).

`AuditLog` é imutável e encadeada (`prev_hash`/`hash`) — escrita só via
`app/services/audit.py`, nunca por UPDATE/DELETE (o role da app não tem
esse GRANT, ver migration 0039). Ao contrário de `PlatformAuditLog`
(plataforma, sem RLS), esta tabela é do tenant e usa RLS normal — quem lê é
o próprio gestor da org.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    TIMESTAMP,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("actor_kind IN ('user', 'bot', 'system')", name="audit_logs_actor_kind_valid"),
        CheckConstraint("result IN ('allow', 'deny')", name="audit_logs_result_valid"),
        Index("idx_audit_logs_org_created", "organization_id", "created_at"),
        Index("idx_audit_logs_org_actor", "organization_id", "actor_user_id"),
        Index("idx_audit_logs_org_resource", "organization_id", "resource_type", "resource_id"),
        Index("idx_audit_logs_org_action", "organization_id", "action"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="user")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(Text)
    resource_id: Mapped[Optional[str]] = mapped_column(Text)
    before: Mapped[Optional[dict]] = mapped_column(JSONB)
    after: Mapped[Optional[dict]] = mapped_column(JSONB)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(Text)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    prev_hash: Mapped[Optional[str]] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
