"""API de gestão de serviços — acesso restrito a owner e manager."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status as http_status

from app.core.rbac import require_manager_access, resolve_role
from app.deps import get_current_user, get_tenant_db
from models import Service, Unit, UserUnit

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
    is_active: bool

    class Config:
        from_attributes = True


class ServicoIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    category: str = Field(..., pattern="^(cabelo|barba|combo|quimica|estetica)$")
    default_duration_min: int = Field(..., gt=0)
    price: Decimal = Field(..., ge=Decimal("0"))
    cost: Decimal = Field(Decimal("0"), ge=Decimal("0"))


class ServicoUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    category: Optional[str] = Field(None, pattern="^(cabelo|barba|combo|quimica|estetica)$")
    default_duration_min: Optional[int] = Field(None, gt=0)
    price: Optional[Decimal] = Field(None, ge=Decimal("0"))
    cost: Optional[Decimal] = Field(None, ge=Decimal("0"))


# ── Helper: resolve role from DB ───────────────────────────────────────────────

async def _resolve_role(db: AsyncSession, user_id: int, org_id: int) -> str:
    result = await db.execute(
        select(UserUnit)
        .join(Unit, UserUnit.unit_id == Unit.id)
        .where(
            UserUnit.user_id == user_id,
            Unit.organization_id == org_id,
        )
    )
    return resolve_role(result.scalars().all())


def _svc_out(s: Service) -> ServicoOut:
    return ServicoOut(
        id=s.id,
        name=s.name,
        category=str(s.category.value) if hasattr(s.category, "value") else str(s.category),
        default_duration_min=s.default_duration_min,
        price=float(s.price),
        cost=float(s.cost),
        is_active=s.is_active,
    )


# ── GET /servicos ─────────────────────────────────────────────────────────────

@router.get("/servicos", response_model=list[ServicoOut])
async def listar_servicos(
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    role = await _resolve_role(db, current_user["user_id"], current_user["org"])
    require_manager_access(role)

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
    current_user: dict = Depends(get_current_user),
):
    role = await _resolve_role(db, current_user["user_id"], current_user["org"])
    require_manager_access(role)

    svc = Service(
        organization_id=current_user["org"],
        name=body.name,
        category=body.category,
        default_duration_min=body.default_duration_min,
        price=body.price,
        cost=body.cost,
    )
    db.add(svc)
    await db.flush()

    out = _svc_out(svc)
    await db.commit()
    return out


# ── PATCH /servicos/{id} ──────────────────────────────────────────────────────

@router.patch("/servicos/{id}", response_model=ServicoOut)
async def atualizar_servico(
    body: ServicoUpdate,
    id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    role = await _resolve_role(db, current_user["user_id"], current_user["org"])
    require_manager_access(role)

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

    await db.flush()
    out = _svc_out(svc)
    await db.commit()
    return out


# ── PATCH /servicos/{id}/arquivar ─────────────────────────────────────────────

@router.patch("/servicos/{id}/arquivar", response_model=ServicoOut)
async def arquivar_servico(
    id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    role = await _resolve_role(db, current_user["user_id"], current_user["org"])
    require_manager_access(role)

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
    current_user: dict = Depends(get_current_user),
):
    role = await _resolve_role(db, current_user["user_id"], current_user["org"])
    require_manager_access(role)

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
