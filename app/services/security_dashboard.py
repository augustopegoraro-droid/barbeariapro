"""Painel de segurança para gestores (Fase 5, ARQUITETURA_ALVO.md §3).

Agregações puras sobre `audit_logs`/`sessions` — sem tabela nova. Todas as
métricas são calculadas sob RLS (a sessão já está escopada à org do request).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import local_date, today_local
from models import AuditLog, User, UserSession

_ANOMALY_MIN_DENIES = 5
_ANOMALY_MULTIPLIER = 3


@dataclass
class DayCount:
    day: str
    logins: int
    denied: int


async def dashboard_summary(
    db: AsyncSession, organization_id: int, days: int = 30
) -> dict:
    days = max(1, min(days, 90))
    since_day = today_local() - timedelta(days=days - 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    day_col = local_date(AuditLog.created_at)

    login_rows = (
        await db.execute(
            select(day_col.label("day"), func.count().label("cnt"))
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.action == "auth.login")
            .where(AuditLog.result == "allow")
            .where(AuditLog.created_at >= cutoff)
            .group_by(day_col)
        )
    ).all()
    denied_rows = (
        await db.execute(
            select(day_col.label("day"), func.count().label("cnt"))
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.result == "deny")
            .where(AuditLog.created_at >= cutoff)
            .group_by(day_col)
        )
    ).all()
    logins_by_day = {r.day: r.cnt for r in login_rows}
    denied_by_day = {r.day: r.cnt for r in denied_rows}
    series = [
        DayCount(
            day=(since_day + timedelta(days=i)).isoformat(),
            logins=logins_by_day.get(since_day + timedelta(days=i), 0),
            denied=denied_by_day.get(since_day + timedelta(days=i), 0),
        )
        for i in range(days)
    ]

    active_users = (
        await db.execute(
            select(func.count(func.distinct(AuditLog.actor_user_id)))
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.actor_user_id.is_not(None))
            .where(AuditLog.created_at >= cutoff)
        )
    ).scalar_one()
    denied_total = sum(d.denied for d in series)
    logins_total = sum(d.logins for d in series)
    connected_devices = (
        await db.execute(
            select(func.count())
            .select_from(UserSession)
            .where(UserSession.organization_id == organization_id)
            .where(UserSession.revoked_at.is_(None))
        )
    ).scalar_one()
    exports_total = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.action.ilike("%.export"))
            .where(AuditLog.result == "allow")
            .where(AuditLog.created_at >= cutoff)
        )
    ).scalar_one()
    permission_changes_total = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .where(
                AuditLog.action.ilike("security.roles%")
                | AuditLog.action.ilike("security.users%")
                | AuditLog.resource_type.in_(["user_role", "permission_override", "role"])
            )
            .where(AuditLog.created_at >= cutoff)
        )
    ).scalar_one()
    critical_actions_total = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.result == "allow")
            .where(~AuditLog.action.ilike("auth.%"))
            .where(AuditLog.created_at >= cutoff)
        )
    ).scalar_one()

    top_denied_rows = (
        await db.execute(
            select(AuditLog.action, func.count().label("cnt"))
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.result == "deny")
            .where(AuditLog.created_at >= cutoff)
            .group_by(AuditLog.action)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()

    recent_denied_rows = (
        await db.execute(
            select(AuditLog, User.email)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(AuditLog.organization_id == organization_id)
            .where(AuditLog.result == "deny")
            .order_by(AuditLog.id.desc())
            .limit(5)
        )
    ).all()

    anomaly = _detect_anomaly(series)

    return {
        "days": days,
        "cards": {
            "logins_total": logins_total,
            "active_users": active_users,
            "denied_total": denied_total,
            "connected_devices": connected_devices,
            "exports_total": exports_total,
            "permission_changes_total": permission_changes_total,
            "critical_actions_total": critical_actions_total,
        },
        "series": [
            {"day": d.day, "logins": d.logins, "denied": d.denied} for d in series
        ],
        "top_denied_actions": [
            {"action": r.action, "count": r.cnt} for r in top_denied_rows
        ],
        "recent_denied": [
            {
                "id": row.id,
                "action": row.action,
                "actor_email": email,
                "reason": row.reason,
                "created_at": row.created_at,
            }
            for row, email in recent_denied_rows
        ],
        "anomaly": anomaly,
    }


def _detect_anomaly(series: list[DayCount]) -> Optional[dict]:
    """Pico de tentativas negadas: últimas 24h vs média dos 7 dias anteriores.

    Heurística inicial (mesma cautela do D-69: sem base real de incidentes
    ainda) — limiar mínimo absoluto evita alarme por ruído em bases pequenas.
    """
    if len(series) < 2:
        return None
    today = series[-1]
    baseline_window = series[-8:-1] if len(series) >= 8 else series[:-1]
    if not baseline_window:
        return None
    baseline_avg = sum(d.denied for d in baseline_window) / len(baseline_window)
    threshold = max(_ANOMALY_MIN_DENIES, baseline_avg * _ANOMALY_MULTIPLIER)
    if today.denied < threshold:
        return None
    return {
        "message": (
            f"{today.denied} tentativa(s) negada(s) hoje — "
            f"média dos últimos {len(baseline_window)} dias foi "
            f"{baseline_avg:.1f}."
        ),
        "today_denied": today.denied,
        "baseline_avg": round(baseline_avg, 1),
    }
