# file: app/authz.py
"""Guard central de autorização (dependência de rota) + contexto de permissões.

Substitui os guards por-papel espalhados (`require_full_access`/`require_manager_access`)
por um único ponto que exige permissões nomeadas. Um endpoint declara
`Depends(require("finance.revenue.view"))`; o guard resolve as permissões efetivas
(sob RLS) e nega (403) por padrão se faltar — fechando a classe de erro
"esqueci a checagem" (V4/V5/V6/V7 da auditoria).

Para filtragem por campo (§1.4.5), o endpoint recebe o `AuthContext` e consulta
`ctx.has("finance.margin.view")` antes de expor o campo sensível — nunca deixando
a decisão para o frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_tenant_db
from app.services.authz import resolve_permissions
from models import User


@dataclass
class AuthContext:
    """Usuário autenticado + suas permissões efetivas na org atual."""

    user: User
    permissions: frozenset[str]

    def has(self, code: str) -> bool:
        return code in self.permissions

    def require(self, code: str) -> None:
        """Levanta 403 se faltar a permissão (uso imperativo dentro do handler)."""
        if code not in self.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permissão necessária: {code}",
            )


async def get_auth_context(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AuthContext:
    """Carrega o usuário e resolve suas permissões efetivas (sob RLS)."""
    perms = await resolve_permissions(db, user)
    return AuthContext(user=user, permissions=perms)


async def require_permission(db: AsyncSession, user: User, code: str) -> None:
    """Checagem imperativa de permissão para call-sites que já têm `db` + `user`.

    Substitui os guards legados por-papel (`require_full_access`/`require_manager_access`)
    preservando a semântica: cada endpoint mapeia para a permissão cujo conjunto de
    papéis reproduz o guard antigo. 403 se faltar (fail-closed)."""
    perms = await resolve_permissions(db, user)
    if code not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permissão necessária: {code}",
        )


def require(*permissions: str):
    """Dependência de rota que exige TODAS as permissões dadas (AND).

    Uso: `_: AuthContext = Depends(require("finance.revenue.view"))`.
    Retorna o `AuthContext` para permitir filtragem por campo no handler.
    """

    async def _dep(
        ctx: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> AuthContext:
        missing = [p for p in permissions if p not in ctx.permissions]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permissão necessária: {', '.join(missing)}",
            )
        return ctx

    return _dep
