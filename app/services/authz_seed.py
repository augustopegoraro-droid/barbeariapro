# file: app/services/authz_seed.py
"""Sincroniza o catálogo de permissões e os papéis de sistema no banco.

Idempotente. Faz upsert de `permissions`, `roles` (sistema, org NULL) e
`role_permissions` a partir da FONTE ÚNICA (`app/core/permissions.py`). É uma
operação de SEED/DEPLOY (sync, roda como dono do banco, ignora RLS) — não é
chamada em runtime pelo app. Usada por `scripts/seed.py` e
`scripts/sync_authz_catalog.py`.

Deve ser rodada sempre que `app/core/permissions.py` mudar. O teste
`tests/test_authz_catalog.py` guarda contra drift entre código e banco.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.permissions import CATALOG, ROLE_DEFAULTS, SYSTEM_ROLES
from models import Permission, Role, RolePermission


def sync_system_catalog(session: Session) -> dict:
    """Upsert do catálogo + papéis de sistema + suas permissões. Retorna um resumo."""
    # 1. permissions (upsert por code)
    for p in CATALOG:
        session.execute(
            pg_insert(Permission.__table__)
            .values(
                code=p.code,
                description=p.description,
                category=p.category,
                is_sensitive_field=p.sensitive_field,
            )
            .on_conflict_do_update(
                index_elements=["code"],
                set_={
                    "description": p.description,
                    "category": p.category,
                    "is_sensitive_field": p.sensitive_field,
                },
            )
        )
    code_to_id: dict[str, int] = dict(
        session.execute(select(Permission.code, Permission.id)).all()
    )

    # 2. papéis de sistema (org NULL) — get-or-update
    slug_to_role_id: dict[str, int] = {}
    for r in SYSTEM_ROLES:
        role = session.execute(
            select(Role).where(Role.slug == r.slug, Role.organization_id.is_(None))
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                organization_id=None,
                slug=r.slug,
                name=r.name,
                color=r.color,
                icon=r.icon,
                is_system=True,
                is_assignable=r.is_assignable,
            )
            session.add(role)
            session.flush()
        else:
            role.name = r.name
            role.color = r.color
            role.icon = r.icon
            role.is_system = True
            role.is_assignable = r.is_assignable
        slug_to_role_id[r.slug] = role.id

    # 3. role_permissions dos papéis de sistema (substituição limpa)
    total_grants = 0
    for slug, role_id in slug_to_role_id.items():
        session.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.organization_id.is_(None),
            )
        )
        for code in sorted(ROLE_DEFAULTS.get(slug, frozenset())):
            pid = code_to_id.get(code)
            if pid is None:  # pragma: no cover - drift protegido por teste
                continue
            session.add(
                RolePermission(
                    role_id=role_id, permission_id=pid, organization_id=None
                )
            )
            total_grants += 1
    session.flush()
    return {
        "permissions": len(CATALOG),
        "system_roles": len(SYSTEM_ROLES),
        "role_permissions": total_grants,
    }
