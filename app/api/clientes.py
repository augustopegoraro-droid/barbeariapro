"""Endpoint de clientes com snapshot de fidelidade."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel, field_validator
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.phone import normalize_phone as _validate_phone
from app.core.rbac import require_full_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from models import Client, ClientLoyalty, User
from models.enums import ContactChannel, LoyaltyNivel, LoyaltyStatus

router = APIRouter(prefix="/clientes", tags=["clientes"])


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
    name: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Nome não pode ser vazio")
        return v.strip() if v else v

    @field_validator("phone")
    @classmethod
    def phone_e164(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_phone(v)


class ClientCreateIn(BaseModel):
    name: str
    phone: str
    acquisition_channel: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Nome não pode ser vazio")
        return v

    @field_validator("phone")
    @classmethod
    def phone_e164(cls, v: str) -> str:
        return _validate_phone(v)

    @field_validator("acquisition_channel")
    @classmethod
    def valid_channel(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        valid = {e.value for e in ContactChannel}
        if v not in valid:
            raise ValueError(f"Canal inválido: {v!r}. Válidos: {sorted(valid)}")
        return v


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
    require_full_access(await resolve_current_role(db, current_user))

    count_rows = (
        await db.execute(
            select(ClientLoyalty.status, func.count(ClientLoyalty.id).label("cnt"))
            .join(Client, Client.id == ClientLoyalty.client_id)
            .where(Client.deleted_at.is_(None))
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


@router.post("", response_model=ClientOut, status_code=http_status.HTTP_201_CREATED)
async def create_cliente(
    body: ClientCreateIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ClientOut:
    require_full_access(await resolve_current_role(db, current_user))

    acq = ContactChannel(body.acquisition_channel) if body.acquisition_channel else None

    client = Client(
        organization_id=current_user.organization_id,
        name=body.name,
        phone_e164=body.phone,
        acquisition_channel=acq,
        is_blocked=False,
    )
    db.add(client)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Telefone já cadastrado nesta organização",
        )

    # Novo cliente nunca tem loyalty — construir resposta sem acessar relacionamento lazy
    response = ClientOut(
        id=client.id,
        name=client.name,
        phone=client.phone_e164,
        acquisition_channel=acq.value if acq else None,
        member_since=datetime.now(timezone.utc).date().isoformat(),
        loyalty=None,
        is_blocked=False,
    )
    await db.commit()
    return response


@router.patch("/{client_id}", response_model=ClientOut)
async def edit_cliente(
    client_id: int,
    body: ClientEditIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ClientOut:
    require_full_access(await resolve_current_role(db, current_user))

    client = (
        await db.execute(
            select(Client)
            .options(selectinload(Client.loyalty))
            .where(Client.id == client_id, Client.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    if body.name is not None:
        client.name = body.name
    if body.phone is not None:
        client.phone_e164 = body.phone

    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Telefone já cadastrado nesta organização",
        )

    response = _to_client_out(client)
    await db.commit()
    return response


@router.delete("/{client_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_cliente(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    require_full_access(await resolve_current_role(db, current_user))

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
    require_full_access(await resolve_current_role(db, current_user))

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
