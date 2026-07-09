"""Emissão de eventos de auditoria (Fase 4, ARQUITETURA_ALVO.md §1.7).

`record_event` é fire-and-forget: agenda a escrita numa Task própria (sessão
nova via `AsyncSessionLocal`/`set_current_org`, molde
`app/services/calendar_sync.py::push_appointment`) para não acrescentar
latência ao request que gerou o evento — não há worker/fila separada porque o
projeto não tem infra de fila (Redis é só dado efêmero) nem processo de worker
(cron é sempre n8n batendo em endpoints `/internal/*`); a Task do próprio
processo é o "assíncrono" possível sem infra nova, documentado como trade-off.

Cada linha inclui o hash da anterior da mesma org (`prev_hash`), travado com
`pg_advisory_xact_lock` (mesmo padrão de `scheduling.py` para numeração
atômica) para serializar concorrência sem duas escritas correndo com o mesmo
`prev_hash`. `wait_for_pending` existe só para testes determinísticos.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, set_current_org
from models import AuditLog

_log = logging.getLogger(__name__)
_pending: set[asyncio.Task] = set()


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)


def _json_safe(value: Optional[dict]) -> Optional[dict]:
    """Normaliza `before`/`after` para tipos que o driver serializa em JSONB
    sem erro (ex.: `datetime`/`Decimal` viram string, molde `_canonical`)."""
    if value is None:
        return None
    return json.loads(_canonical(value))


def _compute_hash(prev_hash: Optional[str], payload: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update((prev_hash or "").encode("utf-8"))
    digest.update(b"|")
    digest.update(_canonical(payload).encode("utf-8"))
    return digest.hexdigest()


async def _write(
    session: AsyncSession,
    *,
    organization_id: int,
    actor_user_id: Optional[int],
    actor_kind: str,
    action: str,
    resource_type: Optional[str],
    resource_id: Optional[str],
    before: Optional[dict],
    after: Optional[dict],
    result: str,
    reason: Optional[str],
    ip: Optional[str],
    user_agent: Optional[str],
) -> None:
    before = _json_safe(before)
    after = _json_safe(after)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"audit_logs:{organization_id}"},
    )
    prev_hash = (
        await session.execute(
            select(AuditLog.hash)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    created_at = datetime.now(timezone.utc)
    payload = {
        "organization_id": organization_id,
        "actor_user_id": actor_user_id,
        "actor_kind": actor_kind,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "before": before,
        "after": after,
        "result": result,
        "reason": reason,
        "created_at": created_at.isoformat(),
    }
    session.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            actor_kind=actor_kind,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
            result=result,
            reason=reason,
            ip=ip,
            user_agent=user_agent,
            prev_hash=prev_hash,
            hash=_compute_hash(prev_hash, payload),
            created_at=created_at,
        )
    )


async def _run_background(organization_id: int, kwargs: dict[str, Any]) -> None:
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await set_current_org(session, organization_id)
                await _write(session, organization_id=organization_id, **kwargs)
    except Exception:
        _log.exception(
            "audit.record_event: falha ao gravar [org=%s action=%s]",
            organization_id, kwargs.get("action"),
        )


def record_event(
    *,
    organization_id: int,
    action: str,
    result: str = "allow",
    actor_user_id: Optional[int] = None,
    actor_kind: str = "user",
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    reason: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Agenda a gravação do evento sem bloquear o caller (fire-and-forget)."""
    kwargs = dict(
        actor_user_id=actor_user_id,
        actor_kind=actor_kind,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id and str(resource_id),
        before=before,
        after=after,
        result=result,
        reason=reason,
        ip=ip,
        user_agent=user_agent,
    )
    task = asyncio.ensure_future(_run_background(organization_id, kwargs))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def wait_for_pending() -> None:
    """Aguarda todas as gravações agendadas (uso em testes, determinístico)."""
    tasks = list(_pending)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def purge_expired() -> int:
    """Apaga linhas além da retenção por org, via `app_audit_purge_expired`
    (SECURITY DEFINER — cobre todas as orgs numa única chamada, sem RLS)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(text("SELECT app_audit_purge_expired()"))
            return result.scalar_one()
