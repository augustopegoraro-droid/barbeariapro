"""Configuração de visibilidade do site público (Fase 6, ARQUITETURA_ALVO.md §1.9)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ClientVisibilitySettings

_DEFAULT_SELECTION = {"mode": "all", "ids": []}
_DEFAULT_BANNER = {"enabled": False}
_DEFAULT_PUBLIC_INFO: dict = {}


async def get_or_create(db: AsyncSession, organization_id: int) -> ClientVisibilitySettings:
    row = (
        await db.execute(
            select(ClientVisibilitySettings).where(
                ClientVisibilitySettings.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row

    row = ClientVisibilitySettings(
        organization_id=organization_id,
        services=dict(_DEFAULT_SELECTION),
        professionals=dict(_DEFAULT_SELECTION),
        banner=dict(_DEFAULT_BANNER),
        public_info=dict(_DEFAULT_PUBLIC_INFO),
    )
    db.add(row)
    await db.flush()
    return row
