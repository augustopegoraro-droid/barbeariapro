"""CRM — funil/Kanban de leads.

Aditivo e isolado por organização (RLS). Não toca no bot/n8n nem dispara
mensagens; apenas gere os cards do funil e seu histórico.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.phone import normalize_phone as _validate_phone
from app.core.rbac import require_full_access
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from models import Lead, LeadEvent, User
from models.enums import ContactChannel, LeadStage

router = APIRouter(prefix="/crm", tags=["crm"])

# Ordem das colunas do Kanban (esquerda → direita).
STAGE_ORDER: tuple[LeadStage, ...] = (
    LeadStage.novo_contato,
    LeadStage.conversando,
    LeadStage.agendado,
    LeadStage.concluido,
    LeadStage.perdido,
)


# ─────────────────────────────── Schemas ────────────────────────────────
class LeadEventOut(BaseModel):
    id: int
    event_type: str
    from_stage: Optional[str]
    to_stage: Optional[str]
    note: Optional[str]
    created_at: str


class LeadOut(BaseModel):
    id: int
    name: str
    phone: Optional[str]
    source: Optional[str]
    stage: str
    position: int
    notes: Optional[str]
    client_id: Optional[int]
    assigned_user_id: Optional[int]
    last_contact_at: Optional[str]
    created_at: str
    updated_at: str


class LeadDetailOut(LeadOut):
    events: List[LeadEventOut]


class BoardColumnOut(BaseModel):
    stage: str
    count: int
    leads: List[LeadOut]


class BoardOut(BaseModel):
    columns: List[BoardColumnOut]


class LeadCreateIn(BaseModel):
    name: str
    phone: Optional[str] = None
    source: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None
    client_id: Optional[int] = None
    assigned_user_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Nome não pode ser vazio")
        return v

    @field_validator("phone")
    @classmethod
    def phone_e164(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return _validate_phone(v)

    @field_validator("source")
    @classmethod
    def valid_source(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in {e.value for e in ContactChannel}:
            raise ValueError(f"Canal inválido: {v!r}")
        return v

    @field_validator("stage")
    @classmethod
    def valid_stage(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in {e.value for e in LeadStage}:
            raise ValueError(f"Estágio inválido: {v!r}")
        return v


class LeadEditIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = None
    assigned_user_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Nome não pode ser vazio")
        return v.strip() if v else v

    @field_validator("phone")
    @classmethod
    def phone_e164(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return _validate_phone(v)

    @field_validator("source")
    @classmethod
    def valid_source(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in {e.value for e in ContactChannel}:
            raise ValueError(f"Canal inválido: {v!r}")
        return v


class LeadMoveIn(BaseModel):
    stage: str
    position: Optional[int] = None

    @field_validator("stage")
    @classmethod
    def valid_stage(cls, v: str) -> str:
        if v not in {e.value for e in LeadStage}:
            raise ValueError(f"Estágio inválido: {v!r}")
        return v


# ─────────────────────────────── Helpers ────────────────────────────────
def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _lead_out(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id,
        name=lead.name,
        phone=lead.phone_e164,
        source=lead.source.value if lead.source else None,
        stage=lead.stage.value,
        position=lead.position,
        notes=lead.notes,
        client_id=lead.client_id,
        assigned_user_id=lead.assigned_user_id,
        last_contact_at=_iso(lead.last_contact_at),
        created_at=_iso(lead.created_at),
        updated_at=_iso(lead.updated_at),
    )


async def _next_position(db: AsyncSession, org_id: int, stage: LeadStage) -> int:
    """Próxima posição (fim da coluna) para um estágio."""
    max_pos = (
        await db.execute(
            select(func.max(Lead.position)).where(
                Lead.organization_id == org_id, Lead.stage == stage
            )
        )
    ).scalar_one_or_none()
    return (max_pos + 1) if max_pos is not None else 0


async def _get_lead(db: AsyncSession, lead_id: int) -> Lead:
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Lead não encontrado"
        )
    return lead


# ─────────────────────────────── Endpoints ──────────────────────────────
@router.get("/board", response_model=BoardOut)
async def get_board(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> BoardOut:
    """Kanban completo: todas as colunas (mesmo vazias) com seus leads."""
    require_full_access(await resolve_current_role(db, current_user))

    rows = (
        await db.execute(select(Lead).order_by(Lead.stage, Lead.position, Lead.id))
    ).scalars().all()

    by_stage: dict[LeadStage, list[LeadOut]] = {s: [] for s in STAGE_ORDER}
    for lead in rows:
        by_stage.setdefault(lead.stage, []).append(_lead_out(lead))

    columns = [
        BoardColumnOut(stage=s.value, count=len(by_stage[s]), leads=by_stage[s])
        for s in STAGE_ORDER
    ]
    return BoardOut(columns=columns)


@router.post("/leads", response_model=LeadOut, status_code=http_status.HTTP_201_CREATED)
async def create_lead(
    body: LeadCreateIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> LeadOut:
    require_full_access(await resolve_current_role(db, current_user))
    org_id = current_user.organization_id

    stage = LeadStage(body.stage) if body.stage else LeadStage.novo_contato
    lead = Lead(
        organization_id=org_id,
        name=body.name,
        phone_e164=body.phone,
        source=ContactChannel(body.source) if body.source else None,
        stage=stage,
        position=await _next_position(db, org_id, stage),
        notes=body.notes,
        client_id=body.client_id,
        assigned_user_id=body.assigned_user_id,
    )
    db.add(lead)
    await db.flush()

    db.add(
        LeadEvent(
            lead_id=lead.id,
            organization_id=org_id,
            event_type="created",
            to_stage=stage,
            created_by_user_id=current_user.id,
        )
    )
    await db.flush()
    response = _lead_out(lead)
    await db.commit()
    return response


@router.get("/leads/{lead_id}", response_model=LeadDetailOut)
async def get_lead(
    lead_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> LeadDetailOut:
    require_full_access(await resolve_current_role(db, current_user))
    lead = (
        await db.execute(
            select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.events))
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Lead não encontrado"
        )
    base = _lead_out(lead)
    events = [
        LeadEventOut(
            id=e.id,
            event_type=e.event_type,
            from_stage=e.from_stage.value if e.from_stage else None,
            to_stage=e.to_stage.value if e.to_stage else None,
            note=e.note,
            created_at=_iso(e.created_at),
        )
        for e in lead.events
    ]
    return LeadDetailOut(**base.model_dump(), events=events)


@router.patch("/leads/{lead_id}", response_model=LeadOut)
async def edit_lead(
    lead_id: int,
    body: LeadEditIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> LeadOut:
    require_full_access(await resolve_current_role(db, current_user))
    lead = await _get_lead(db, lead_id)

    if body.name is not None:
        lead.name = body.name
    if body.phone is not None:
        lead.phone_e164 = body.phone
    if body.notes is not None:
        lead.notes = body.notes
    if body.source is not None:
        lead.source = ContactChannel(body.source)
    if body.assigned_user_id is not None:
        lead.assigned_user_id = body.assigned_user_id
    lead.updated_at = datetime.now(timezone.utc)

    await db.flush()
    response = _lead_out(lead)
    await db.commit()
    return response


@router.post("/leads/{lead_id}/move", response_model=LeadOut)
async def move_lead(
    lead_id: int,
    body: LeadMoveIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> LeadOut:
    """Move o card para outro estágio/posição e registra o histórico."""
    require_full_access(await resolve_current_role(db, current_user))
    org_id = current_user.organization_id
    lead = await _get_lead(db, lead_id)

    new_stage = LeadStage(body.stage)
    old_stage = lead.stage
    new_position = (
        body.position
        if body.position is not None
        else await _next_position(db, org_id, new_stage)
    )

    changed_stage = new_stage != old_stage
    lead.stage = new_stage
    lead.position = new_position
    lead.updated_at = datetime.now(timezone.utc)

    if changed_stage:
        db.add(
            LeadEvent(
                lead_id=lead.id,
                organization_id=org_id,
                event_type="stage_changed",
                from_stage=old_stage,
                to_stage=new_stage,
                created_by_user_id=current_user.id,
            )
        )

    await db.flush()
    response = _lead_out(lead)
    await db.commit()
    return response


@router.delete("/leads/{lead_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    require_full_access(await resolve_current_role(db, current_user))
    lead = await _get_lead(db, lead_id)
    await db.delete(lead)
    await db.commit()
