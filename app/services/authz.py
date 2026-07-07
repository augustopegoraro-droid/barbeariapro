# file: app/services/authz.py
"""Resolução de permissões efetivas de um usuário (RBAC + overrides).

Estratégia (ARQUITETURA_ALVO.md §1.4.2), robusta a banco não-semeado:
- O papel de SISTEMA primário vem de `user_units` (mecanismo legado, inalterado)
  e suas permissões vêm do CÓDIGO (`app/core/permissions.py`) — não dependem de
  seed no banco, então a autorização nunca "abre" nem "fecha" por falta de seed.
- Papéis ADICIONAIS/personalizados via `user_roles`: se de sistema, permissões do
  código; se personalizado, permissões de `role_permissions` (banco).
- `permission_overrides` aplicam allow/deny por usuário (deny vence).

Tudo roda sob a sessão do tenant (`get_tenant_db`) → RLS garante o escopo de org.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import permissions_for_system_role
from app.core.rbac import resolve_role
from models import (
    Permission,
    PermissionOverride,
    Role,
    RolePermission,
    Unit,
    User,
    UserRole,
    UserUnit,
)


async def _unit_links(db: AsyncSession, user: User) -> list[UserUnit]:
    """Vínculos usuário↔unidade escopados à org (join com `units`, que tem RLS)."""
    rows = (
        await db.execute(
            select(UserUnit)
            .join(Unit, Unit.id == UserUnit.unit_id)
            .where(UserUnit.user_id == user.id)
        )
    ).scalars().all()
    return list(rows)


async def resolve_permissions(db: AsyncSession, user: User) -> frozenset[str]:
    """Conjunto de códigos de permissão efetivos do usuário na org atual."""
    # 1. papel de sistema primário (legado) → permissões do código
    perms: set[str] = set(permissions_for_system_role(resolve_role(await _unit_links(db, user))))

    # 2. papéis adicionais/personalizados via user_roles
    rows = (
        await db.execute(
            select(Role.slug, Role.id, Role.is_system)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
    ).all()
    custom_role_ids: list[int] = []
    for slug, role_id, is_system in rows:
        if is_system:
            perms |= set(permissions_for_system_role(slug))
        else:
            custom_role_ids.append(role_id)
    if custom_role_ids:
        codes = (
            await db.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id.in_(custom_role_ids))
            )
        ).scalars().all()
        perms |= set(codes)

    # 3. overrides por usuário (deny vence)
    overrides = (
        await db.execute(
            select(Permission.code, PermissionOverride.effect)
            .join(PermissionOverride, PermissionOverride.permission_id == Permission.id)
            .where(PermissionOverride.user_id == user.id)
        )
    ).all()
    for code, effect in overrides:
        if effect == "allow":
            perms.add(code)
        elif effect == "deny":
            perms.discard(code)

    return frozenset(perms)
