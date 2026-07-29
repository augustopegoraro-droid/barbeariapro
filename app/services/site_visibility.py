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


async def ensure_visible(
    db: AsyncSession, organization_id: int, kind: str, object_id: int
) -> None:
    """Mantém no site público um profissional/serviço recém-cadastrado (D-84).

    `kind` é "professionals" ou "services". Só age quando o gestor usa whitelist
    (`mode == "custom"`): sem isso, um cadastro novo nasceria invisível no site e
    "adicionar funcionário" não teria efeito nenhum na vitrine. O padrão é
    `mode == "all"` — nesse caso (e quando a org nunca abriu a tela de
    visibilidade) não há nada a fazer.

    Decisão: cadastrar já publica. Para esconder, o gestor desmarca em
    `/admin/seguranca/visibilidade`.
    """
    if kind not in ("professionals", "services"):  # pragma: no cover — erro de programação
        raise ValueError(f"kind inválido: {kind}")

    row = (
        await db.execute(
            select(ClientVisibilitySettings).where(
                ClientVisibilitySettings.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return

    selection = getattr(row, kind) or {}
    if selection.get("mode") != "custom":
        return

    ids = {int(i) for i in selection.get("ids", [])}
    if object_id in ids:
        return
    # reatribuir (JSONB sem MutableDict não detecta mutação in-place)
    setattr(row, kind, {**selection, "mode": "custom", "ids": sorted(ids | {object_id})})
    await db.flush()
