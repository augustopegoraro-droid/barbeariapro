"""Superadmin da PLATAFORMA (dono do SaaS).

Tabelas GLOBAIS do domínio de plataforma, conceitualmente separadas de `users`
(que opera UMA barbearia): não estão sob RLS e o role `barber_app` não tem
GRANT direto — o acesso pela aplicação é feito apenas via funções
`SECURITY DEFINER` (migrations 0021/0030). Ver `app/services/platform.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    text,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PlatformAdmin(Base):
    __tablename__ = "platform_admins"
    __table_args__ = (
        UniqueConstraint("email", name="platform_admins_email_unique"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class PlatformAuditLog(Base):
    """Auditoria imutável das ações da PLATAFORMA (superadmin M9/M10).

    Toda ação sensível do superadmin vira linha aqui: suspensão, troca de
    plano, mudanças de assinatura, alterações financeiras, reset de senha,
    impersonação. Molde estrito de `platform_admins`: sem RLS e SEM GRANT —
    escrita/leitura só via funções SECURITY DEFINER (append-only de fato:
    não existe função de UPDATE/DELETE).
    """

    __tablename__ = "platform_audit_log"
    __table_args__ = (
        CheckConstraint(
            "category IN ('impersonation', 'subscription', 'financial', "
            "'security', 'org', 'onboarding')",
            name="platform_audit_category_valid",
        ),
        Index("idx_platform_audit_org", "organization_id"),
        Index("idx_platform_audit_category", "category"),
        Index("idx_platform_audit_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("platform_admins.id", ondelete="RESTRICT"),
        nullable=False,
    )
    admin_email: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    organization_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    ip: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class PlatformOnboardingOverride(Base):
    """Marcação MANUAL de etapa de onboarding pela plataforma.

    As etapas são derivadas dos dados reais da org (serviço
    `onboarding_progress`); um override registra a exceção humana — `done`
    true/false vence a derivação. Remover o override volta ao automático.
    Mesmo molde de acesso das demais tabelas de plataforma (sem RLS/GRANT).
    """

    __tablename__ = "platform_onboarding_overrides"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "stage_key", name="platform_onboarding_org_stage_unique"
        ),
        CheckConstraint(
            "length(btrim(stage_key)) > 0", name="platform_onboarding_stage_nonempty"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stage_key: Mapped[str] = mapped_column(Text, nullable=False)
    done: Mapped[bool] = mapped_column(nullable=False)
    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("platform_admins.id", ondelete="RESTRICT"),
        nullable=False,
    )
    admin_email: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class PlatformOrgNote(Base):
    """Nota interna do superadmin sobre uma org (suporte/CS).

    Visível SÓ para a plataforma — nunca para o tenant (por isso sem RLS/GRANT:
    o tenant não pode nem saber que a tabela existe). `admin_email` é snapshot
    denormalizado para exibição estável mesmo se o admin for removido.
    """

    __tablename__ = "platform_org_notes"
    __table_args__ = (
        CheckConstraint("length(btrim(body)) > 0", name="platform_org_notes_body_nonempty"),
        Index("idx_platform_org_notes_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("platform_admins.id", ondelete="RESTRICT"),
        nullable=False,
    )
    admin_email: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
