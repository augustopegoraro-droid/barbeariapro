"""Pedidos de remarcação de atendimentos (barbeiro cria → gestor aprova).

- Barbeiro: `POST /remarcacoes` cria um pedido para os PRÓPRIOS atendimentos.
- Gestor (owner/manager): `GET /remarcacoes` lista, `GET /remarcacoes/pendentes/count`
  alimenta o badge do sino, `PATCH /remarcacoes/{id}` aprova/recusa.

O RBAC é por endpoint (não por prefixo). A aprovação NÃO move os atendimentos
automaticamente — é sinalização para o gestor agir (follow-up).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_manager_access
from app.deps import (
    get_current_user,
    get_tenant_db,
    resolve_current_role,
    resolve_current_role_with_barber,
)
from app.services import reschedule as svc
from models import AppointmentRescheduleRequest, User

router = APIRouter(prefix="/remarcacoes", tags=["remarcacoes"])


# ─── schemas ─────────────────────────────────────────────────────────────────

class RescheduleCreateIn(BaseModel):
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    reason: Optional[str] = Field(None, max_length=2000)


class RescheduleReviewIn(BaseModel):
    approve: bool
    note: Optional[str] = Field(None, max_length=2000)


class RescheduleOut(BaseModel):
    id: int
    barber_id: int
    barber_name: Optional[str] = None
    requested_by_user_id: Optional[int] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    reason: Optional[str] = None
    status: str
    source: str
    reviewed_by_user_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    created_at: datetime


class PendingCountOut(BaseModel):
    count: int


def _to_out(req: AppointmentRescheduleRequest) -> RescheduleOut:
    return RescheduleOut(
        id=req.id,
        barber_id=req.barber_id,
        barber_name=req.barber.name if req.barber is not None else None,
        requested_by_user_id=req.requested_by_user_id,
        period_start=req.period_start,
        period_end=req.period_end,
        reason=req.reason,
        status=req.status,
        source=req.source,
        reviewed_by_user_id=req.reviewed_by_user_id,
        reviewed_at=req.reviewed_at,
        review_note=req.review_note,
        created_at=req.created_at,
    )


# ─── barbeiro: criar pedido ──────────────────────────────────────────────────

@router.post("", response_model=RescheduleOut, status_code=http_status.HTTP_201_CREATED)
async def criar_remarcacao(
    body: RescheduleCreateIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> RescheduleOut:
    role, barber_id = await resolve_current_role_with_barber(db, current_user)
    if barber_id is None:
        # Só o barbeiro solicita a remarcação dos próprios atendimentos.
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Apenas barbeiros podem solicitar remarcação de atendimentos.",
        )
    req = await svc.create_request(
        db,
        organization_id=current_user.organization_id,
        barber_id=barber_id,
        requested_by_user_id=current_user.id,
        period_start=body.period_start,
        period_end=body.period_end,
        reason=body.reason,
        source="app",
    )
    await db.refresh(req, attribute_names=["barber"])
    return _to_out(req)


# ─── gestor: listar / contar / decidir ───────────────────────────────────────

@router.get("", response_model=list[RescheduleOut])
async def listar_remarcacoes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    status: Annotated[Optional[str], Query()] = "pendente",
) -> list[RescheduleOut]:
    require_manager_access(await resolve_current_role(db, current_user))
    rows = await svc.list_requests(db, status=status)
    return [_to_out(r) for r in rows]


@router.get("/pendentes/count", response_model=PendingCountOut)
async def contar_pendentes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PendingCountOut:
    require_manager_access(await resolve_current_role(db, current_user))
    return PendingCountOut(count=await svc.count_pending(db))


@router.patch("/{request_id}", response_model=RescheduleOut)
async def decidir_remarcacao(
    request_id: Annotated[int, Path(gt=0)],
    body: RescheduleReviewIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> RescheduleOut:
    require_manager_access(await resolve_current_role(db, current_user))
    req = await svc.review_request(
        db,
        request_id=request_id,
        approve=body.approve,
        reviewed_by_user_id=current_user.id,
        note=body.note,
    )
    await db.refresh(req, attribute_names=["barber"])
    return _to_out(req)
