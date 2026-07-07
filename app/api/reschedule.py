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
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.core.rbac import require_manager_access
from app.deps import (
    get_current_user,
    get_tenant_db,
    resolve_current_role,
    resolve_current_role_with_barber,
)
from app.services import reschedule as svc
from models import AppointmentRescheduleRequest, User
from models.appointment_reschedule import RESCHEDULE_STATUSES

router = APIRouter(prefix="/remarcacoes", tags=["remarcacoes"])


# ─── schemas ─────────────────────────────────────────────────────────────────

class RescheduleCreateIn(BaseModel):
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    reason: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _check_period_order(self) -> "RescheduleCreateIn":
        # Só valida quando ambos os limites vêm preenchidos — pedido sem período
        # (ex.: Kernel IA por texto livre) é legítimo. `>` estrito, igual ao CHECK
        # de DB (migration 0027) e ao padrão de TimeOff/Appointment.
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end <= self.period_start
        ):
            raise ValueError("period_end deve ser depois de period_start")
        return self


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

# Filtro ?status= : vazio ou uma destas sentinelas → todos os status.
_STATUS_ALL = {"", "todas", "todos", "all"}


@router.get("", response_model=list[RescheduleOut])
async def listar_remarcacoes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    status: Annotated[Optional[str], Query()] = "pendente",
) -> list[RescheduleOut]:
    await require_permission(db, current_user, "schedule.reschedule.approve")
    # Normaliza o filtro: vazio/sentinela → todos; valor do catálogo → filtra;
    # qualquer outra coisa → 422 (nunca [] silencioso). `status=None` na service
    # devolve todos os status.
    raw = (status or "").strip().lower()
    if raw in _STATUS_ALL:
        effective: Optional[str] = None
    elif raw in RESCHEDULE_STATUSES:
        effective = raw
    else:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"status inválido: {status!r}. "
                f"Use um de {list(RESCHEDULE_STATUSES)} ou 'todas'."
            ),
        )
    rows = await svc.list_requests(db, status=effective)
    return [_to_out(r) for r in rows]


@router.get("/pendentes/count", response_model=PendingCountOut)
async def contar_pendentes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PendingCountOut:
    await require_permission(db, current_user, "schedule.reschedule.approve")
    return PendingCountOut(count=await svc.count_pending(db))


@router.patch("/{request_id}", response_model=RescheduleOut)
async def decidir_remarcacao(
    request_id: Annotated[int, Path(gt=0)],
    body: RescheduleReviewIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> RescheduleOut:
    await require_permission(db, current_user, "schedule.reschedule.approve")
    req = await svc.review_request(
        db,
        request_id=request_id,
        approve=body.approve,
        reviewed_by_user_id=current_user.id,
        note=body.note,
    )
    await db.refresh(req, attribute_names=["barber"])
    return _to_out(req)
