"""Núcleo de autorização (RBAC por permissões + ABAC).

Tabelas (migration 0037):
- `permissions`      — catálogo GLOBAL de permissões (sem RLS; referência).
- `roles`            — papéis de sistema (organization_id NULL) + personalizados por org.
- `role_permissions` — quais permissões cada papel concede.
- `user_roles`       — papéis atribuídos a um usuário (custom/adicionais; o papel de
                       sistema primário continua vindo de `user_units`, ver
                       `app/services/authz.py`).
- `permission_overrides` — exceções por usuário (allow/deny) sobre o papel.

A fonte da verdade das permissões dos papéis de SISTEMA é o código
(`app/core/permissions.py`); estas tabelas espelham o catálogo (via
`sync_system_catalog`) para a UI e sustentam papéis personalizados/overrides.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    is_sensitive_field: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        # slug único por org; papéis de sistema (org NULL) usam índice parcial próprio
        # criado na migration para garantir unicidade do slug global.
        UniqueConstraint("organization_id", "slug", name="roles_slug_per_org"),
        Index("idx_roles_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # NULL = papel de SISTEMA (global, imutável). Preenchido = papel personalizado da org.
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[Optional[str]] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_assignable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )
    # Espelha o org do papel (NULL p/ sistema) — isolamento estrutural sob RLS.
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE")
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "unit_id", name="user_roles_unique"),
        Index("idx_user_roles_org_user", "organization_id", "user_id"),
        Index("idx_user_roles_role", "role_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    # NULL = vale para a org toda; preenchido = escopo de unidade.
    unit_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="CASCADE")
    )
    granted_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class PermissionOverride(Base):
    __tablename__ = "permission_overrides"
    __table_args__ = (
        CheckConstraint(
            "effect IN ('allow', 'deny')", name="permission_overrides_effect_valid"
        ),
        UniqueConstraint(
            "user_id", "permission_id", "unit_id", name="permission_overrides_unique"
        ),
        Index("idx_permission_overrides_org_user", "organization_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )
    effect: Mapped[str] = mapped_column(Text, nullable=False)
    unit_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="CASCADE")
    )
    reason: Mapped[Optional[str]] = mapped_column(Text)
    granted_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
