"""Endpoint de clientes com snapshot de fidelidade."""

from __future__ import annotations

from datetime import datetime, timezone
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
    is_blocked: bool = False


class ClientEditIn(BaseModel):
    name: str


class ClientesOut(BaseModel):
    total: int
    ativo_count: int
    em_risco_count: int
    inativo_count: int
    sem_loyalty_count: int
    clients: list[ClientOut]


def _to_client_out(c: Client) -> ClientOut:
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
    return ClientOut(
        id=c.id,
        name=c.name,
        phone=c.phone_e164,
        acquisition_channel=c.acquisition_channel.value if c.acquisition_channel else None,
        member_since=c.created_at.date().isoformat(),
        loyalty=loyalty_out,
        is_blocked=c.is_blocked,
    )


@router.get("", response_model=ClientesOut)
async def get_clientes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    status: Optional[str] = Query(None),
    nivel: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ClientesOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    require_full_access(resolve_role(list(unit_links)))

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
        base_q = base_q.where(ClientLoyalty.status == LoyaltyStatus(status))

    if nivel in ("novo", "ativo", "fiel", "vip"):
        base_q = base_q.where(ClientLoyalty.nivel == LoyaltyNivel(nivel))

    filtered_total = (
        await db.execute(select(func.count()).select_from(base_q.subquery()))
    ).scalar_one()

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

    return ClientesOut(
        total=filtered_total,
        ativo_count=count_map.get("ativo", 0),
        em_risco_count=count_map.get("em_risco", 0),
        inativo_count=count_map.get("inativo", 0),
        sem_loyalty_count=total_clients - total_with_loyalty,
        clients=[_to_client_out(c) for c in clients],
    )


@router.patch("/{client_id}", response_model=ClientOut)
async def edit_cliente(
    client_id: int,
    body: ClientEditIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ClientOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    require_full_access(resolve_role(list(unit_links)))

    client = (
        await db.execute(
            select(Client)
            .options(selectinload(Client.loyalty))
            .where(Client.id == client_id, Client.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    client.name = body.name.strip()
    response = _to_client_out(client)
    await db.commit()
    return response


@router.delete("/{client_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_cliente(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    require_full_access(resolve_role(list(unit_links)))

    client = (
        await db.execute(
            select(Client).where(Client.id == client_id, Client.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    client.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.patch("/{client_id}/bloquear", response_model=ClientOut)
async def bloquear_cliente(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ClientOut:
    unit_links = (
        await db.execute(select(UserUnit).where(UserUnit.user_id == current_user.id))
    ).scalars().all()
    require_full_access(resolve_role(list(unit_links)))

    client = (
        await db.execute(
            select(Client)
            .options(selectinload(Client.loyalty))
            .where(Client.id == client_id, Client.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    client.is_blocked = not client.is_blocked
    response = _to_client_out(client)
    await db.commit()
    return response
