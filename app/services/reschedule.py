"""Pedidos de remarcação de atendimentos — camada de dados (sob RLS do tenant).

Usada pelo router `/remarcacoes` e pelo dispatch do Kernel IA. Todas as queries
rodam na sessão do tenant (RLS filtra por `organization_id`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import AppointmentRescheduleRequest

_TERMINAL = {"aprovada": True, "recusada": True}


async def create_request(
    db: AsyncSession,
    *,
    organization_id: int,
    barber_id: int,
    requested_by_user_id: Optional[int],
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
    reason: Optional[str] = None,
    source: str = "app",
) -> AppointmentRescheduleRequest:
    req = AppointmentRescheduleRequest(
        organization_id=organization_id,
        barber_id=barber_id,
        requested_by_user_id=requested_by_user_id,
        period_start=period_start,
        period_end=period_end,
        reason=reason,
        status="pendente",
        source=source,
    )
    db.add(req)
    await db.flush()
    await db.refresh(req)
    return req


async def list_requests(
    db: AsyncSession, *, status: Optional[str] = None
) -> list[AppointmentRescheduleRequest]:
    stmt = (
        select(AppointmentRescheduleRequest)
        .options(selectinload(AppointmentRescheduleRequest.barber))
        # F8: `id` desempata created_at iguais (inserts na mesma transação
        # compartilham func.now()) → ordem estável, nunca indefinida.
        .order_by(
            AppointmentRescheduleRequest.created_at.desc(),
            AppointmentRescheduleRequest.id.desc(),
        )
    )
    if status is not None:
        stmt = stmt.where(AppointmentRescheduleRequest.status == status)
    return list((await db.execute(stmt)).scalars().all())


async def count_pending(db: AsyncSession) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(AppointmentRescheduleRequest)
            .where(AppointmentRescheduleRequest.status == "pendente")
        )
    ).scalar_one()


async def review_request(
    db: AsyncSession,
    *,
    request_id: int,
    approve: bool,
    reviewed_by_user_id: int,
    note: Optional[str] = None,
) -> AppointmentRescheduleRequest:
    """Aprova ou recusa um pedido pendente. 404 se não existe (ou é de outro
    tenant — RLS); 409 se já foi decidido."""
    req = (
        await db.execute(
            select(AppointmentRescheduleRequest)
            .where(AppointmentRescheduleRequest.id == request_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Pedido de remarcação não encontrado.",
        )
    if req.status in _TERMINAL:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Pedido já está '{req.status}'.",
        )
    req.status = "aprovada" if approve else "recusada"
    req.reviewed_by_user_id = reviewed_by_user_id
    req.reviewed_at = func.now()
    req.review_note = note
    await db.flush()
    await db.refresh(req)
    return req
