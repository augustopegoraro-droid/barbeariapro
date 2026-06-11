"""Endpoint de clientes com snapshot de fidelidade."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import require_full_access, resolve_role
from app.deps import get_current_user, get_tenant_db
from models import Client, ClientLoyalty, User, UserUnit
from models.enums import LoyaltyNivel, LoyaltyStatus

router = APIRouter(prefix="/clientes", tags=["clientes"])

_NIVEL_ORDER = {
    LoyaltyNivel.vip: 4,
    LoyaltyNivel.fiel: 3,
    LoyaltyNivel.ativo: 2,
    LoyaltyNivel.novo: 1,
}


class LoyaltyOut(BaseModel):
    nivel: str
    status: str
    categoria: Optional[str]
    visit_count: int
    total_spent: float
    last_visit_at: Optional[str]


class ClientOut(BaseModel):
    id: int
    name: str
    phone: str
    acquisition_channel: Optional[str]
    member_since: str
    loyalty: Optional[LoyaltyOut]


class ClientesOut(BaseModel):
    total: int
    ativo_count: int
    em_risco_count: int
    inativo_count: int
    sem_loyalty_count: int
    clients: list[ClientOut]


@router.get("", response_model=ClientesOut)
async def get_clientes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    status: Optional[str] = Query(None, description="Filtrar por status: ativo, em_risco, inativo, sem_registro"),
    nivel: Optional[str] = Query(None, description="Filtrar por nível: novo, ativo, fiel, vip"),
    search: Optional[str] = Query(None, description="Busca por nome ou telefone"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ClientesOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    require_full_access(resolve_role(list(unit_links)))

    # Contadores do summary (sem filtros de paginação)
    count_rows = (
        await db.execute(
            select(ClientLoyalty.status, func.count(ClientLoyalty.id).label("cnt"))
            .group_by(ClientLoyalty.status)
        )
    ).all()

    count_map = {r.status.value: r.cnt for r in count_rows}
    total_with_loyalty = sum(count_map.values())

    total_clients = (
        await db.execute(
            select(func.count(Client.id)).where(Client.deleted_at.is_(None))
        )
    ).scalar_one()

    # Query base com filtros (search, status, nivel)
    base_q = (
        select(Client)
        .outerjoin(ClientLoyalty, ClientLoyalty.client_id == Client.id)
        .where(Client.deleted_at.is_(None))
    )

    if search:
        term = f"%{search.lower()}%"
        base_q = base_q.where(
            func.lower(Client.name).like(term) | Client.phone_e164.like(term)
        )

    if status == "sem_registro":
        base_q = base_q.where(ClientLoyalty.id.is_(None))
    elif status in ("ativo", "em_risco", "inativo"):
        loyalty_status = LoyaltyStatus(status)
        base_q = base_q.where(ClientLoyalty.status == loyalty_status)

    if nivel in ("novo", "ativo", "fiel", "vip"):
        loyalty_nivel = LoyaltyNivel(nivel)
        base_q = base_q.where(ClientLoyalty.nivel == loyalty_nivel)

    # Total filtrado (para paginação correta)
    filtered_total = (
        await db.execute(
            select(func.count()).select_from(base_q.subquery())
        )
    ).scalar_one()

    # Ordenação e paginação
    status_order = case(
        (ClientLoyalty.status == LoyaltyStatus.em_risco, 1),
        (ClientLoyalty.status == LoyaltyStatus.ativo, 2),
        (ClientLoyalty.status == LoyaltyStatus.inativo, 3),
        else_=4,
    )
    q = (
        base_q
        .options(selectinload(Client.loyalty))
        .order_by(status_order.asc(), Client.name.asc())
        .limit(limit)
        .offset(offset)
    )
    clients = (await db.execute(q)).scalars().unique().all()

    result = []
    for c in clients:
        loyalty_out: Optional[LoyaltyOut] = None
        if c.loyalty:
            lv = c.loyalty
            loyalty_out = LoyaltyOut(
                nivel=lv.nivel.value,
                status=lv.status.value,
                categoria=lv.categoria.value if lv.categoria else None,
                visit_count=lv.visit_count,
                total_spent=float(lv.total_spent),
                last_visit_at=lv.last_visit_at.isoformat() if lv.last_visit_at else None,
            )
        result.append(
            ClientOut(
                id=c.id,
                name=c.name,
                phone=c.phone_e164,
                acquisition_channel=c.acquisition_channel.value if c.acquisition_channel else None,
                member_since=c.created_at.date().isoformat(),
                loyalty=loyalty_out,
            )
        )

    return ClientesOut(
        total=filtered_total,
        ativo_count=count_map.get("ativo", 0),
        em_risco_count=count_map.get("em_risco", 0),
        inativo_count=count_map.get("inativo", 0),
        sem_loyalty_count=total_clients - total_with_loyalty,
        clients=result,
    )
