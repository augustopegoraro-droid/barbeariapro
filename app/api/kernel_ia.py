"""Kernel IA — endpoint do assistente in-app (chat).

`POST /kernel-ia/query {prompt}` → `{intent, message, taskId?}`. Autenticado (JWT do
tenant), multi-tenant via RLS. **RBAC por capacidade:** o serviço filtra as tools pelo
papel (gestor = tools de negócio; barbeiro = agenda + solicitar remarcação). A lógica de
LLM + tools + RBAC mora em `app/services/kernel_ia.py`.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_tenant_db, resolve_current_role_with_barber
from app.services import kernel_ia
from models import Unit, User

router = APIRouter(prefix="/kernel-ia", tags=["kernel-ia"])

TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


class QueryIn(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)


class QueryOut(BaseModel):
    # by_alias na resposta → devolve `taskId` (camelCase) p/ o frontend.
    model_config = ConfigDict(populate_by_name=True)

    intent: str
    message: str
    task_id: Optional[str] = Field(default=None, alias="taskId")


async def _primary_unit_id(db: AsyncSession) -> Optional[int]:
    return (
        await db.execute(
            select(Unit.id).where(Unit.deleted_at.is_(None)).order_by(Unit.id).limit(1)
        )
    ).scalar_one_or_none()


@router.post("/query", response_model=QueryOut, response_model_by_alias=True)
async def query(body: QueryIn, db: TenantDB, current_user: CurrentUser) -> QueryOut:
    role, barber_id = await resolve_current_role_with_barber(db, current_user)
    unit_id = await _primary_unit_id(db)
    result = await kernel_ia.answer(
        db,
        body.prompt,
        role=role,
        org_id=current_user.organization_id,
        unit_id=unit_id,
        barber_id=barber_id,
        user_id=current_user.id,
    )
    return QueryOut(
        intent=result["intent"], message=result["message"], task_id=result.get("task_id")
    )
