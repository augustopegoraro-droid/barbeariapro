"""Camada de dados do painel de PLATAFORMA (superadmin).

Wrappers async das funções `SECURITY DEFINER` da migration 0021 (molde de
`app/services/tenant.py`). Todas operam numa sessão **sem tenant** (`get_db`) —
as funções SQL ignoram a RLS (rodam como dono) e o role do app é NOBYPASSRLS,
então um SELECT cross-org direto retornaria 0 linhas.

Regra de ouro: o endpoint de plataforma **nunca** seta `app.current_org_id` na
própria sessão. Operações que precisam escopar uma org específica (onboarding,
patch/suspend/reactivate) usam sessões helper isoladas (ver `onboarding.py` e o
router) — não esta camada.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def admin_login(db: AsyncSession, email: str) -> Optional[dict]:
    """`{id, password_hash}` do superadmin com o e-mail (case-insensitive), ou None."""
    if not email or not email.strip():
        return None
    row = (
        await db.execute(
            text("SELECT id, password_hash FROM app_platform_admin_login(:e)"),
            {"e": email.strip().lower()},
        )
    ).first()
    if row is None:
        return None
    return {"id": row.id, "password_hash": row.password_hash}


async def admin_exists(db: AsyncSession, admin_id: int) -> bool:
    """True se o superadmin ainda existe (revalidação do guard a cada request)."""
    found = (
        await db.execute(
            text("SELECT app_platform_admin_exists(:i)"), {"i": admin_id}
        )
    ).scalar_one_or_none()
    return found is not None


async def list_orgs(db: AsyncSession) -> list[dict]:
    """Todas as orgs (id, name, subdomain, plano, status da assinatura, datas).

    `status` exposto ao cliente é derivado no router: `suspended` se `deleted_at`,
    senão o `sub_status` da assinatura."""
    rows = (await db.execute(text("SELECT * FROM app_platform_list_orgs()"))).all()
    return [dict(r._mapping) for r in rows]


async def active_org_ids(db: AsyncSession) -> list[int]:
    """Ids das orgs não-suspensas (deleted_at NULL) — base do loop de MRR."""
    rows = (
        await db.execute(text("SELECT app_platform_active_org_ids()"))
    ).scalars().all()
    return [int(r) for r in rows]


async def usage(db: AsyncSession) -> list[dict]:
    """Uso por tenant (agendamentos 30d, usuários ativos, mensagens do bot 30d,
    última atividade) — para detectar churn."""
    rows = (await db.execute(text("SELECT * FROM app_platform_usage()"))).all()
    return [dict(r._mapping) for r in rows]


async def create_org(
    db: AsyncSession, *, name: str, subdomain: Optional[str], plan_id: int
) -> int:
    """Cria organização + assinatura (status trial, +365d) e devolve o novo org_id.

    Os filhos (unidade/owner/serviços) são semeados por `onboarding.provision_org`.
    """
    new_id = (
        await db.execute(
            text("SELECT app_platform_create_org(:n, :s, :p)"),
            {"n": name, "s": subdomain, "p": plan_id},
        )
    ).scalar_one()
    return int(new_id)
