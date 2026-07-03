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


async def org_overview(db: AsyncSession) -> list[dict]:
    """Visão rica por org (plano, assinatura, contagens, uso) — tabela do painel."""
    rows = (await db.execute(text("SELECT * FROM app_platform_org_overview()"))).all()
    return [dict(r._mapping) for r in rows]


async def org_profile(db: AsyncSession, org_id: int) -> Optional[dict]:
    """Perfil completo de UMA org (cadastro + assinatura vigente + plano), ou None."""
    row = (
        await db.execute(
            text("SELECT * FROM app_platform_org_profile(:o)"), {"o": org_id}
        )
    ).first()
    return dict(row._mapping) if row is not None else None


async def org_users(db: AsyncSession, org_id: int) -> list[dict]:
    """Usuários da org com papéis agregados (cross-tenant, leitura de suporte)."""
    rows = (
        await db.execute(
            text("SELECT * FROM app_platform_org_users(:o)"), {"o": org_id}
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def org_barbers(db: AsyncSession, org_id: int) -> list[dict]:
    """Profissionais da org (inclui desativados — soft delete visível ao suporte)."""
    rows = (
        await db.execute(
            text("SELECT * FROM app_platform_org_barbers(:o)"), {"o": org_id}
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def org_subscriptions(db: AsyncSession, org_id: int) -> list[dict]:
    """Histórico completo de assinaturas da org (mais recente primeiro)."""
    rows = (
        await db.execute(
            text("SELECT * FROM app_platform_org_subscriptions(:o)"), {"o": org_id}
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def org_notes_list(db: AsyncSession, org_id: int) -> list[dict]:
    """Notas internas da plataforma sobre a org (nunca visíveis ao tenant)."""
    rows = (
        await db.execute(
            text("SELECT * FROM app_platform_org_notes_list(:o)"), {"o": org_id}
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def org_note_add(
    db: AsyncSession, org_id: int, admin_id: int, body: str
) -> Optional[dict]:
    """Registra nota interna. None se o admin não existir (função não insere).

    O commit é do ciclo de vida da sessão do request (`get_db` usa
    `session.begin()`) — não commitar aqui.
    """
    row = (
        await db.execute(
            text("SELECT * FROM app_platform_org_note_add(:o, :a, :b)"),
            {"o": org_id, "a": admin_id, "b": body},
        )
    ).first()
    return dict(row._mapping) if row is not None else None


async def onboarding_signals(db: AsyncSession) -> list[dict]:
    """Sinais crus de onboarding por org ativa (uma linha por org)."""
    rows = (
        await db.execute(text("SELECT * FROM app_platform_onboarding_signals()"))
    ).all()
    return [dict(r._mapping) for r in rows]


async def onboarding_overrides(db: AsyncSession) -> dict[int, dict[str, bool]]:
    """Overrides manuais agrupados: {org_id: {stage_key: done}}."""
    rows = (
        await db.execute(text("SELECT * FROM app_platform_onboarding_overrides()"))
    ).all()
    grouped: dict[int, dict[str, bool]] = {}
    for r in rows:
        grouped.setdefault(r.organization_id, {})[r.stage_key] = r.done
    return grouped


async def onboarding_override_set(
    db: AsyncSession, org_id: int, stage_key: str, done: bool, admin_id: int
) -> Optional[dict]:
    """Grava/atualiza override manual. None se o admin não existir."""
    row = (
        await db.execute(
            text("SELECT * FROM app_platform_onboarding_override_set(:o, :k, :d, :a)"),
            {"o": org_id, "k": stage_key, "d": done, "a": admin_id},
        )
    ).first()
    return dict(row._mapping) if row is not None else None


async def onboarding_override_clear(
    db: AsyncSession, org_id: int, stage_key: str
) -> int:
    """Remove o override (volta ao automático). Devolve quantos removeu (0/1)."""
    removed = (
        await db.execute(
            text("SELECT app_platform_onboarding_override_clear(:o, :k)"),
            {"o": org_id, "k": stage_key},
        )
    ).scalar_one()
    return int(removed)


async def audit_add(
    db: AsyncSession,
    admin_id: int,
    *,
    action: str,
    category: str,
    target_type: str,
    target_id: Optional[int] = None,
    org_id: Optional[int] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict] = None,
    ip: Optional[str] = None,
) -> Optional[int]:
    """Registra ação sensível do superadmin (append-only, SECURITY DEFINER)."""
    import json

    row = (
        await db.execute(
            text(
                "SELECT app_platform_audit_add(:a, :ac, :c, :tt, :ti, :o, :r, "
                "CAST(:m AS jsonb), :ip)"
            ),
            {
                "a": admin_id, "ac": action, "c": category, "tt": target_type,
                "ti": target_id, "o": org_id, "r": reason,
                "m": json.dumps(metadata or {}), "ip": ip,
            },
        )
    ).scalar_one_or_none()
    return int(row) if row is not None else None


async def audit_list(
    db: AsyncSession,
    *,
    limit: int = 100,
    category: Optional[str] = None,
    org_id: Optional[int] = None,
) -> list[dict]:
    rows = (
        await db.execute(
            text("SELECT * FROM app_platform_audit_list(:l, :c, :o)"),
            {"l": limit, "c": category, "o": org_id},
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def billing_subscriptions(db: AsyncSession) -> list[dict]:
    """Assinatura mais recente por org + plano + dunning (visão do painel)."""
    rows = (
        await db.execute(text("SELECT * FROM app_platform_billing_subscriptions()"))
    ).all()
    return [dict(r._mapping) for r in rows]


async def metrics_monthly(db: AsyncSession, months: int) -> list[dict]:
    """Série mensal do SaaS (novas orgs, cancelamentos, base ativa/trial, MRR).

    Aproximação por vigência das assinaturas até o billing real (invoices)
    existir — ver docstring da migration 0028."""
    rows = (
        await db.execute(
            text("SELECT * FROM app_platform_metrics_monthly(:m)"), {"m": months}
        )
    ).all()
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
