"""API de gestão de serviços — acesso restrito a owner e manager."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status as http_status

from app.authz import require_permission
from app.core.rbac import require_manager_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from models import Barber, BarberService, Service

router = APIRouter(tags=["servicos"])

CATEGORIES = {"cabelo", "barba", "combo", "quimica", "estetica"}

# ── Schemas ────────────────────────────────────────────────────────────────────

class ServicoOut(BaseModel):
    id: int
    name: str
    category: str
    default_duration_min: int
    price: float
    cost: float
    has_variable_price: bool
    is_active: bool

    class Config:
        from_attributes = True


class ServicoIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    category: str = Field(..., pattern="^(cabelo|barba|combo|quimica|estetica)$")
    default_duration_min: int = Field(..., gt=0)
    price: Decimal = Field(..., ge=Decimal("0"))
    cost: Decimal = Field(Decimal("0"), ge=Decimal("0"))
    has_variable_price: bool = False


class ServicoUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    category: Optional[str] = Field(None, pattern="^(cabelo|barba|combo|quimica|estetica)$")
    default_duration_min: Optional[int] = Field(None, gt=0)
    price: Optional[Decimal] = Field(None, ge=Decimal("0"))
    cost: Optional[Decimal] = Field(None, ge=Decimal("0"))
    has_variable_price: Optional[bool] = None



def _svc_out(s: Service) -> ServicoOut:
    return ServicoOut(
        id=s.id,
        name=s.name,
        category=str(s.category.value) if hasattr(s.category, "value") else str(s.category),
        default_duration_min=s.default_duration_min,
        price=float(s.price),
        cost=float(s.cost),
        has_variable_price=s.has_variable_price,
        is_active=s.is_active,
    )


# ── GET /servicos ─────────────────────────────────────────────────────────────

@router.get("/servicos", response_model=list[ServicoOut])
async def listar_servicos(
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_tenant_db),
    current_user = Depends(get_current_user),
):
    await require_permission(db, current_user, "services.manage")

    stmt = select(Service).order_by(Service.name)
    if not include_inactive:
        stmt = stmt.where(Service.is_active.is_(True))
    result = await db.execute(stmt)
    return [_svc_out(s) for s in result.scalars().all()]


# ── POST /servicos ────────────────────────────────────────────────────────────

@router.post("/servicos", response_model=ServicoOut, status_code=http_status.HTTP_201_CREATED)
async def criar_servico(
    body: ServicoIn,
    db: AsyncSession = Depends(get_tenant_db),
    current_user = Depends(get_current_user),
):
    await require_permission(db, current_user, "services.manage")

    svc = Service(
        organization_id=current_user.organization_id,
        name=body.name,
        category=body.category,
        default_duration_min=body.default_duration_min,
        price=body.price,
        cost=body.cost,
        has_variable_price=body.has_variable_price,
    )
    db.add(svc)
    await db.flush()

    # Vincular o serviço novo a todos os barbeiros ativos — espelha criar_barbeiro,
    # que vincula um barbeiro novo a todos os serviços. Sem isto o serviço fica
    # inagendável (agenda exige BarberService). Política atual: "todos com todos".
    barber_ids = (
        await db.execute(select(Barber.id).where(Barber.deleted_at.is_(None)))
    ).scalars().all()
    for bid in barber_ids:
        db.add(BarberService(barber_id=bid, service_id=svc.id))

    out = _svc_out(svc)
    await db.commit()
    return out


# ── PATCH /servicos/{id} ──────────────────────────────────────────────────────

@router.patch("/servicos/{id}", response_model=ServicoOut)
async def atualizar_servico(
    body: ServicoUpdate,
    id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_tenant_db),
    current_user = Depends(get_current_user),
):
    await require_permission(db, current_user, "services.manage")

    result = await db.execute(select(Service).where(Service.id == id))
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Serviço não encontrado.")

    if body.name is not None:
        svc.name = body.name
    if body.category is not None:
        svc.category = body.category
    if body.default_duration_min is not None:
        svc.default_duration_min = body.default_duration_min
    if body.price is not None:
        svc.price = body.price
    if body.cost is not None:
        svc.cost = body.cost
    if body.has_variable_price is not None:
        svc.has_variable_price = body.has_variable_price

    await db.flush()
    out = _svc_out(svc)
    await db.commit()
    return out


# ── PATCH /servicos/{id}/arquivar ─────────────────────────────────────────────

@router.patch("/servicos/{id}/arquivar", response_model=ServicoOut)
async def arquivar_servico(
    id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_tenant_db),
    current_user = Depends(get_current_user),
):
    await require_permission(db, current_user, "services.manage")

    result = await db.execute(select(Service).where(Service.id == id))
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Serviço não encontrado.")
    if not svc.is_active:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail="Serviço já está arquivado.")

    svc.is_active = False
    await db.flush()
    out = _svc_out(svc)
    await db.commit()
    return out


# ── PATCH /servicos/{id}/reativar ─────────────────────────────────────────────

@router.patch("/servicos/{id}/reativar", response_model=ServicoOut)
async def reativar_servico(
    id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_tenant_db),
    current_user = Depends(get_current_user),
):
    await require_permission(db, current_user, "services.manage")

    result = await db.execute(select(Service).where(Service.id == id))
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Serviço não encontrado.")
    if svc.is_active:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail="Serviço já está ativo.")

    svc.is_active = True
    await db.flush()
    out = _svc_out(svc)
    await db.commit()
    return out
