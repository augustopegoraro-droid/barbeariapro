"""Sugestão de compra de produto (barbeiro/recepção sugere → gestor decide).

- Equipe operacional (`purchases.request`): `POST /compras-sugeridas` cria uma
  sugestão — não é o pedido de compra formal (D-93), é uma nota pendente de
  aprovação.
- Gestor (`purchases.manage`): `GET /compras-sugeridas` lista,
  `GET /compras-sugeridas/pendentes/count` alimenta o badge do sino,
  `PATCH /compras-sugeridas/{id}` aprova/recusa.

O RBAC é por endpoint (não por prefixo). Molde de `app/api/reschedule.py`
(D-57), estendendo o mesmo padrão de "solicitação pendente de aprovação" para
compras (D-98).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http_status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import require_permission
from app.deps import get_current_user, get_tenant_db
from app.services import purchase_requests as svc
from app.services.audit import record_event
from models import ProductPurchaseRequest, User
from models.product_purchase_request import PURCHASE_REQUEST_STATUSES

router = APIRouter(prefix="/compras-sugeridas", tags=["compras-sugeridas"])


# ─── schemas ─────────────────────────────────────────────────────────────────

class PurchaseRequestCreateIn(BaseModel):
    variant_id: Optional[int] = Field(None, gt=0)
    product_name: Optional[str] = Field(None, max_length=200)
    quantidade_sugerida: Optional[Decimal] = Field(None, gt=0)
    motivo: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _check_target(self) -> "PurchaseRequestCreateIn":
        if self.variant_id is None and not (self.product_name and self.product_name.strip()):
            raise ValueError("Informe `variant_id` ou `product_name`.")
        return self


class PurchaseRequestReviewIn(BaseModel):
    approve: bool
    note: Optional[str] = Field(None, max_length=2000)


class PurchaseRequestOut(BaseModel):
    id: int
    variant_id: Optional[int] = None
    variant_name: Optional[str] = None
    product_name: Optional[str] = None
    qty_suggested: Optional[Decimal] = None
    reason: Optional[str] = None
    status: str
    source: str
    requested_by_user_id: Optional[int] = None
    reviewed_by_user_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    created_at: datetime


class PendingCountOut(BaseModel):
    count: int


def _to_out(req: ProductPurchaseRequest) -> PurchaseRequestOut:
    variant = req.variant
    variant_name = None
    product_name = req.product_name
    if variant is not None:
        variant_name = variant.name
        product_name = product_name or (variant.product.name if variant.product else None)
    return PurchaseRequestOut(
        id=req.id,
        variant_id=req.variant_id,
        variant_name=variant_name,
        product_name=product_name,
        qty_suggested=req.qty_suggested,
        reason=req.reason,
        status=req.status,
        source=req.source,
        requested_by_user_id=req.requested_by_user_id,
        reviewed_by_user_id=req.reviewed_by_user_id,
        reviewed_at=req.reviewed_at,
        review_note=req.review_note,
        created_at=req.created_at,
    )


# ─── equipe: sugerir compra ───────────────────────────────────────────────────

@router.post("", response_model=PurchaseRequestOut, status_code=http_status.HTTP_201_CREATED)
async def criar_sugestao(
    body: PurchaseRequestCreateIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PurchaseRequestOut:
    await require_permission(db, current_user, "purchases.request")
    req = await svc.create_request(
        db,
        organization_id=current_user.organization_id,
        requested_by_user_id=current_user.id,
        variant_id=body.variant_id,
        product_name=body.product_name,
        qty_suggested=body.quantidade_sugerida,
        reason=body.motivo,
        source="app",
    )
    await db.refresh(req, attribute_names=["variant"])
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="purchases.request.create",
        resource_type="product_purchase_request",
        resource_id=req.id,
        after={"variant_id": req.variant_id, "product_name": req.product_name},
    )
    return _to_out(req)


# ─── gestor: listar / contar / decidir ────────────────────────────────────────

_STATUS_ALL = {"", "todas", "todos", "all"}


@router.get("", response_model=list[PurchaseRequestOut])
async def listar_sugestoes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    status: Annotated[Optional[str], Query()] = "pendente",
) -> list[PurchaseRequestOut]:
    await require_permission(db, current_user, "purchases.manage")
    raw = (status or "").strip().lower()
    if raw in _STATUS_ALL:
        effective: Optional[str] = None
    elif raw in PURCHASE_REQUEST_STATUSES:
        effective = raw
    else:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"status inválido: {status!r}. "
                f"Use um de {list(PURCHASE_REQUEST_STATUSES)} ou 'todas'."
            ),
        )
    rows = await svc.list_requests(db, status=effective)
    return [_to_out(r) for r in rows]


@router.get("/pendentes/count", response_model=PendingCountOut)
async def contar_pendentes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PendingCountOut:
    await require_permission(db, current_user, "purchases.manage")
    return PendingCountOut(count=await svc.count_pending(db))


@router.patch("/{request_id}", response_model=PurchaseRequestOut)
async def decidir_sugestao(
    request_id: Annotated[int, Path(gt=0)],
    body: PurchaseRequestReviewIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PurchaseRequestOut:
    await require_permission(db, current_user, "purchases.manage")
    req = await svc.review_request(
        db,
        request_id=request_id,
        approve=body.approve,
        reviewed_by_user_id=current_user.id,
        note=body.note,
    )
    await db.refresh(req, attribute_names=["variant"])
    record_event(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        action="purchases.request.review",
        resource_type="product_purchase_request",
        resource_id=req.id,
        after={"status": req.status},
    )
    return _to_out(req)
