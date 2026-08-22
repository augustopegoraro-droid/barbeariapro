# file: app/services/webhook_log.py
"""Registro bruto de webhooks — porta única de idempotência (`webhook_events`).

A tabela nasceu no billing SaaS (D-61, migration 0032) e é reaproveitada por
qualquer gateway: o `UNIQUE (provider, event_id)` isola os fluxos entre si
(`provider="stripe"` = mensalidade da barbearia; `provider="stripe_connect"` =
compra de assinatura pelo cliente final).

O contrato é o mesmo dos dois lados:

1. `record_raw_event(...)` grava o payload BRUTO com `ON CONFLICT DO NOTHING`.
   Devolve o id da linha quando é a primeira vez, **None quando é replay** —
   é o `None` que autoriza o caller a responder 200 sem reprocessar.
2. `mark_event(...)` fecha o ciclo (`processed`/`skipped`/`failed`) numa
   sessão própria, para que o desfecho fique registrado mesmo se a transação
   de negócio tiver rolado atrás.

`webhook_events` não tem RLS (é log de plataforma, sem tenant garantido no
momento da recepção — a org é resolvida durante o processamento).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal, set_current_org
from models import WebhookEvent


async def record_raw_event(
    *,
    provider: str,
    event_id: str,
    event_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> Optional[int]:
    """Persiste o evento bruto. Retorna o id, ou None se já existia (replay)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            return (
                await session.execute(
                    pg_insert(WebhookEvent)
                    .values(
                        provider=provider,
                        event_id=event_id,
                        event_type=event_type,
                        # Payload BRUTO: é o que permite reprocessar depois.
                        payload=payload or {},
                        status="received",
                    )
                    .on_conflict_do_nothing(index_elements=["provider", "event_id"])
                    .returning(WebhookEvent.id)
                )
            ).scalar_one_or_none()


async def mark_event(
    webhook_id: int,
    status: str,
    *,
    org_id: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Fecha o ciclo do evento (`processed`/`skipped`/`failed`), em sessão própria.

    `webhook_events` tem RLS "global OU tenant" (V18a/D-76): gravar
    `organization_id` numa sessão SEM o GUC violaria o `WITH CHECK`. Por isso,
    quando a org já foi resolvida, a sessão é escopada antes do UPDATE.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            if org_id is not None:
                await set_current_org(session, org_id)
            await session.execute(
                update(WebhookEvent)
                .where(WebhookEvent.id == webhook_id)
                .values(
                    status=status,
                    organization_id=org_id,
                    error=error,
                    attempts=WebhookEvent.attempts + 1,
                    processed_at=datetime.now(timezone.utc),
                )
            )
