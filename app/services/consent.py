"""Registro de consentimento — histórico append-only (Fase 8, ARQUITETURA_ALVO.md §1.11)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models import ConsentRecord


async def record_consent(
    session: AsyncSession,
    *,
    organization_id: int,
    subject_id: int,
    channel: str,
    status: str,
    source: Optional[str] = None,
    ip: Optional[str] = None,
    policy_version: Optional[str] = None,
    subject_type: str = "client",
) -> None:
    """Grava uma linha de histórico — nunca substitui, `ClientConsent` (D-51)
    continua sendo o estado atual lido por `reminders.py`/`reactivation.py`."""
    session.add(
        ConsentRecord(
            organization_id=organization_id,
            subject_type=subject_type,
            subject_id=subject_id,
            channel=channel,
            status=status,
            policy_version=policy_version,
            source=source,
            ip=ip,
        )
    )
