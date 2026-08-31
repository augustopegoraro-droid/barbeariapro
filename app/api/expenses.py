# file: app/api/expenses.py
"""Endpoint interno de despesas recorrentes — cron mensal do n8n (D-102).

Molde de `app/api/reminders.py`: auth via `X-Bot-Token` (`get_bot_db`), org
resolvida pela instância. O dono cria o cron `0 6 1 * *` no n8n (não dá para
automatizar — n8n sem API key). Ver `docs/EXPENSES_CRON_N8N.md`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_local
from app.deps import get_bot_db, get_bot_org_id
from app.services import expenses as expenses_svc

internal_router = APIRouter(prefix="/internal/expenses", tags=["expenses-internal"])
BotDB = Annotated[AsyncSession, Depends(get_bot_db)]
BotOrgId = Annotated[int, Depends(get_bot_org_id)]


class ExpensesRunOut(BaseModel):
    created: int
    skipped: int


@internal_router.post("/run", response_model=ExpensesRunOut)
async def run_expenses(db: BotDB, org_id: BotOrgId) -> ExpensesRunOut:
    """Materializa as despesas recorrentes ativas no mês corrente (1 conta
    `a_pagar` por template). Idempotente — a 2ª chamada no mesmo mês é no-op."""
    result = await expenses_svc.materialize_recurrences(
        db, organization_id=org_id, today=today_local()
    )
    return ExpensesRunOut(**result)
