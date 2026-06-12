# file: app/api/reminders.py
"""Endpoint interno de lembretes — chamado pelo cron horário do n8n."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.deps import get_bot_db
from app.services import reminders as reminders_svc

internal_router = APIRouter(prefix="/internal/reminders", tags=["reminders-internal"])
BotDB = Annotated[AsyncSession, Depends(get_bot_db)]


class RemindersOut(BaseModel):
    sent: int
    skipped: int
    total_targets: int


@internal_router.post("/run", response_model=RemindersOut)
async def run_reminders(db: BotDB) -> RemindersOut:
    """Envia lembretes de agendamento na janela de 24h.

    Chamado pelo cron horário do n8n (auth via X-Bot-Token).
    """
    result = await reminders_svc.run(
        org_id=settings.bot_organization_id, session=db
    )
    return RemindersOut(**result)
