"""Entitlements: o que o plano/assinatura da org permite (superadmin M7).

Três níveis derivados do status da assinatura mais recente (SA-D06):
- `full`      → trial | active
- `restricted`→ past_due | paused | incomplete (bloqueia só recursos pagos)
- `blocked`   → canceled | sem assinatura (suspensão administrativa já é
                barrada no login — organizations.deleted_at)

Limites lidos de `plan_limits` (fallback ao legado max_units/max_barbers).
Enforcement gradual por `BILLING_ENFORCEMENT`:
- off  → não checa nada;
- log  → permite e loga warning (rollout seguro — default);
- hard → bloqueia com 402/403.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from models import Plan, PlanFeature, PlanLimit, Subscription

_logger = logging.getLogger(__name__)

_LEVELS = {
    "trial": "full",
    "active": "full",
    "past_due": "restricted",
    "paused": "restricted",
    "incomplete": "restricted",
    "canceled": "blocked",
}


@dataclass
class Entitlements:
    level: str  # full | restricted | blocked
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    limits: dict[str, Optional[int]] = field(default_factory=dict)  # None = ilimitado
    features: dict[str, bool] = field(default_factory=dict)


async def get_entitlements(db: AsyncSession) -> Entitlements:
    """Entitlements da org da SESSÃO (RLS já escopa — usar com get_tenant_db)."""
    sub = (
        await db.execute(
            select(Subscription)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if sub is None:
        return Entitlements(level="blocked")
    status_value = sub.status.value if hasattr(sub.status, "value") else str(sub.status)
    level = _LEVELS.get(status_value, "restricted")

    plan = (
        await db.execute(select(Plan).where(Plan.id == sub.plan_id))
    ).scalar_one_or_none()
    limits: dict[str, Optional[int]] = {}
    features: dict[str, bool] = {}
    if plan is not None:
        rows = (
            await db.execute(select(PlanLimit).where(PlanLimit.plan_id == plan.id))
        ).scalars().all()
        limits = {r.limit_key: r.value for r in rows}
        # Fallback ao legado enquanto plan_limits não cobre a chave.
        limits.setdefault("units", plan.max_units)
        limits.setdefault("barbers", plan.max_barbers)
        frows = (
            await db.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id))
        ).scalars().all()
        features = {f.feature_key: f.enabled for f in frows}
    return Entitlements(
        level=level,
        plan_id=plan.id if plan else None,
        plan_name=plan.name if plan else None,
        limits=limits,
        features=features,
    )


async def check_limit(db: AsyncSession, limit_key: str, current_count: int) -> None:
    """Barra a CRIAÇÃO de um recurso quando o limite do plano foi atingido.

    `current_count` = quantos já existem ANTES da criação. Comportamento segue
    `BILLING_ENFORCEMENT` (off/log/hard). Recursos existentes nunca são
    destruídos por downgrade — só a criação de novos é bloqueada (SA-D06).
    """
    mode = settings.billing_enforcement
    if mode == "off":
        return
    ent = await get_entitlements(db)
    limit = ent.limits.get(limit_key)
    exceeded = limit is not None and current_count >= limit
    blocked_level = ent.level == "blocked"
    if not exceeded and not blocked_level:
        return
    reason = (
        f"limite '{limit_key}' do plano atingido ({current_count}/{limit})"
        if exceeded
        else "assinatura inativa"
    )
    if mode == "log":
        _logger.warning("entitlements (modo log): %s — criação permitida", reason)
        return
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=f"Recurso indisponível no seu plano: {reason}. Fale com o suporte ou faça upgrade.",
    )
