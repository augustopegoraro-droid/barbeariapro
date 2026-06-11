"""Endpoints do módulo de fidelidade."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.deps import get_bot_db
from app.services import loyalty as loyalty_svc
from app.services import reactivation as reactivation_svc
from models.loyalty import ClientLoyalty

router = APIRouter(prefix="/loyalty", tags=["loyalty"])
internal_router = APIRouter(prefix="/internal/loyalty", tags=["loyalty-internal"])
BotDB = Annotated[AsyncSession, Depends(get_bot_db)]


class LoyaltyOut(BaseModel):
    client_id: int
    visit_count: int
    total_spent: float
    last_visit_at: Optional[str]
    nivel: str
    status: str
    categoria: Optional[str]
    preferred_barber_id: Optional[int]
    preferred_service_id: Optional[int]
    benefit: str
    next_milestone_categoria: str
    next_milestone_nivel: str


class ReactivationOut(BaseModel):
    sent: int
    skipped: int
    total_targets: int


@router.get("/clients/{client_id}", response_model=LoyaltyOut)
async def get_client_loyalty(client_id: int, db: BotDB) -> LoyaltyOut:
    loyalty = (
        await db.execute(
            select(ClientLoyalty).where(ClientLoyalty.client_id == client_id)
        )
    ).scalar_one_or_none()

    if not loyalty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dados de fidelidade não encontrados para este cliente.",
        )

    milestone = loyalty_svc.next_milestone(loyalty.visit_count, loyalty.total_spent)

    return LoyaltyOut(
        client_id=loyalty.client_id,
        visit_count=loyalty.visit_count,
        total_spent=float(loyalty.total_spent),
        last_visit_at=loyalty.last_visit_at.isoformat() if loyalty.last_visit_at else None,
        nivel=loyalty.nivel.value,
        status=loyalty.status.value,
        categoria=loyalty.categoria.value if loyalty.categoria else None,
        preferred_barber_id=loyalty.preferred_barber_id,
        preferred_service_id=loyalty.preferred_service_id,
        benefit=loyalty_svc.resolve_benefit(loyalty.nivel, loyalty.categoria),
        next_milestone_categoria=milestone["categoria"],
        next_milestone_nivel=milestone["nivel"],
    )


@internal_router.post("/reactivation/run", response_model=ReactivationOut)
async def run_reactivation(db: BotDB) -> ReactivationOut:
    """Dispara campanha de reativação para clientes em risco/inativos.

    Chamado pelo cron diário do n8n.
    """
    result = await reactivation_svc.run(
        org_id=settings.bot_organization_id, session=db
    )
    return ReactivationOut(**result)
