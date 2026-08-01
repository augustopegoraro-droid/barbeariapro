"""Registro de consentimento — histórico append-only (Fase 8, ARQUITETURA_ALVO.md §1.11).

`set_consent` é a **porta única** de escrita (D-86): grava o estado atual em
`ClientConsent` (lido por `reminders.py`/`reactivation.py` antes de disparar) e
a linha de histórico em `ConsentRecord` na mesma chamada. Antes disso cada
call-site fazia o upsert à mão e era fácil gravar um sem o outro — o histórico
é a prova, o estado é a decisão de envio; os dois precisam andar juntos.

`record_consent` continua exposta para quem só quer histórico (ex.: backfill de
base legal de dados importados, onde não existe estado a mudar).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.privacy import PRIVACY_POLICY_VERSION
from models import ClientConsent, ConsentRecord, ConsentStatus, ContactChannel


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


async def set_consent(
    session: AsyncSession,
    *,
    organization_id: int,
    client_id: int,
    channel: ContactChannel,
    status: ConsentStatus,
    source: str,
    ip: Optional[str] = None,
    policy_version: Optional[str] = PRIVACY_POLICY_VERSION,
) -> None:
    """Estado atual (upsert em `client_consents`) + histórico, atomicamente.

    `policy_version` default é a versão vigente; passe `None` explicitamente
    quando o consentimento não nasceu de um aceite de política (ex.: opt-out
    por palavra-chave, que é revogação — não há texto aceito).
    """
    await session.execute(
        pg_insert(ClientConsent)
        .values(
            client_id=client_id,
            channel=channel,
            status=status,
            source=source,
        )
        .on_conflict_do_update(
            constraint="client_consents_unique",
            set_={"status": status, "source": source, "updated_at": func.now()},
        )
    )
    await record_consent(
        session,
        organization_id=organization_id,
        subject_id=client_id,
        channel=channel.value,
        status=status.value,
        source=source,
        ip=ip,
        policy_version=policy_version,
    )
