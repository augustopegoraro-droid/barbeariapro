"""Kernel IA — endpoint do assistente in-app (chat).

`POST /kernel-ia/query {prompt}` → `{intent, message}`. Só gestor (owner/manager),
pois expõe dados financeiros. Multi-tenant via RLS do token. A lógica de LLM+tools
mora em `app/services/kernel_ia.py`.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_manager_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.services import kernel_ia
from models import Unit, User

router = APIRouter(prefix="/kernel-ia", tags=["kernel-ia"])

TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


class QueryIn(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)


class QueryOut(BaseModel):
    intent: str
    message: str
    taskId: Optional[str] = None


async def _primary_unit_id(db: AsyncSession) -> Optional[int]:
    return (
        await db.execute(
            select(Unit.id).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1)
        )
    ).scalar_one_or_none()


@router.post("/query", response_model=QueryOut)
async def query(body: QueryIn, db: TenantDB, current_user: CurrentUser) -> QueryOut:
    require_manager_access(await resolve_current_role(db, current_user))
    unit_id = await _primary_unit_id(db)
    result = await kernel_ia.answer(db, body.prompt, unit_id)
    return QueryOut(intent=result["intent"], message=result["message"])
