# file: app/api/platform.py
"""Painel de PLATAFORMA (superadmin do SaaS) — camada ACIMA dos tenants.

Conceitualmente separado do painel de tenant: autenticação própria
(`platform_admins` + JWT com `typ="platform"`, sem `org`), guard próprio
(`require_platform_admin`) — NÃO mistura com o RBAC de tenant
(owner/manager/reception/barber). Nenhum endpoint seta `app.current_org_id` na
sessão do request: leituras/agregações usam funções `SECURITY DEFINER`
(`app/services/platform.py`); escritas escopadas a uma org usam sessões helper
isoladas (`onboarding.py` e os helpers abaixo).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_platform_token,
    decode_access_token,
    verify_password,
)
from app.db.session import AsyncSessionLocal, get_db, set_current_org
from app.services import onboarding as onboarding_svc
from app.services import platform as platform_svc
from app.services.management import mrr
from models import Organization, Subscription

router = APIRouter(prefix="/platform", tags=["platform"])
_bearer = HTTPBearer(auto_error=True)

# Sessão SEM tenant (não seta app.current_org_id). Usada pelas leituras de plataforma.
PlatformDB = Annotated[AsyncSession, Depends(get_db)]


# ─── auth / guard de plataforma ────────────────────────────────────────────────

def get_platform_token_data(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> int:
    """Decodifica o Bearer e exige `typ="platform"`. Devolve o admin_id (sub).

    Um token de tenant (sem `typ`, com `org`) é rejeitado aqui; um token de
    plataforma (sem `org`) é rejeitado pelo guard de tenant. Isolamento bilateral.
    """
    try:
        payload = decode_access_token(creds.credentials)
        if payload.get("typ") != "platform":
            raise ValueError("token não é de plataforma")
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de plataforma inválido ou ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_platform_admin(
    admin_id: Annotated[int, Depends(get_platform_token_data)],
    db: PlatformDB,
) -> int:
    """Revalida que o superadmin ainda existe (via SECURITY DEFINER). 403 senão."""
    if not await platform_svc.admin_exists(db, admin_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin não encontrado.",
        )
    return admin_id


PlatformAdminId = Annotated[int, Depends(require_platform_admin)]


# ─── schemas ────────────────────────────────────────────────────────────────

class PlatformLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class PlatformTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OrgOut(BaseModel):
    id: int
    name: str
    subdomain: Optional[str] = None
    plan_name: Optional[str] = None
    status: str  # 'suspended' | sub_status (trial/active/past_due/canceled) | 'sem_assinatura'
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class OrgCreateIn(BaseModel):
    name: str = Field(..., min_length=1)
    subdomain: Optional[str] = Field(None, description="Slug único (taylor.app.com → 'taylor')")
    plan_id: int = Field(..., gt=0)
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=6)


class OrgCreateOut(BaseModel):
    org_id: int
    unit_id: int
    owner_user_id: int
    services: int


class OrgPatchIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    plan_id: Optional[int] = Field(None, gt=0)


class UsageOut(BaseModel):
    org_id: int
    appt_30d: int
    active_users: int
    bot_msgs_30d: int
    last_activity: Optional[datetime] = None


class DashboardCountsOut(BaseModel):
    total: int
    active: int
    trial: int
    suspended: int


class DashboardOut(BaseModel):
    counts: DashboardCountsOut
    mrr_consolidated: float
    active_subscriptions: int
    usage: list[UsageOut]


# ─── helpers ──────────────────────────────────────────────────────────────────

def _derive_status(row: dict) -> str:
    if row.get("deleted_at") is not None:
        return "suspended"
    return row.get("sub_status") or "sem_assinatura"


# ─── endpoints ──────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=PlatformTokenOut)
async def platform_login(body: PlatformLoginIn, db: PlatformDB) -> PlatformTokenOut:
    admin = await platform_svc.admin_login(db, str(body.email))
    if admin is None or not verify_password(body.password, admin["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
        )
    return PlatformTokenOut(access_token=create_platform_token(admin_id=admin["id"]))


@router.get("/orgs", response_model=list[OrgOut])
async def list_orgs(_admin: PlatformAdminId, db: PlatformDB) -> list[OrgOut]:
    rows = await platform_svc.list_orgs(db)
    return [
        OrgOut(
            id=r["id"],
            name=r["name"],
            subdomain=r["subdomain"],
            plan_name=r["plan_name"],
            status=_derive_status(r),
            created_at=r["created_at"],
            deleted_at=r["deleted_at"],
        )
        for r in rows
    ]


@router.post("/orgs", response_model=OrgCreateOut, status_code=status.HTTP_201_CREATED)
async def create_org(body: OrgCreateIn, _admin: PlatformAdminId) -> OrgCreateOut:
    """Onboarding: cria org + assinatura + unidade + owner + serviços (atômico)."""
    try:
        summary = await onboarding_svc.provision_org(
            name=body.name,
            subdomain=body.subdomain,
            plan_id=body.plan_id,
            owner_email=str(body.owner_email),
            owner_password=body.owner_password,
        )
    except Exception as exc:  # noqa: BLE001 — devolve causa legível (subdomínio dup., plano inexistente)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Falha ao criar org: {exc}",
        )
    return OrgCreateOut(**summary)


@router.patch("/orgs/{org_id}", response_model=OrgOut)
async def patch_org(org_id: int, body: OrgPatchIn, _admin: PlatformAdminId) -> OrgOut:
    """Edita nome e/ou plano da org. Usa sessão helper escopada (RLS) — não a do request."""
    if body.name is None and body.plan_id is None:
        raise HTTPException(status_code=400, detail="Nada para atualizar.")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            org = (
                await session.execute(select(Organization).where(Organization.id == org_id))
            ).scalar_one_or_none()
            if org is None:
                raise HTTPException(status_code=404, detail="Org não encontrada.")
            if body.name is not None:
                org.name = body.name
            if body.plan_id is not None:
                sub = (
                    await session.execute(
                        select(Subscription)
                        .where(Subscription.organization_id == org_id)
                        .order_by(Subscription.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if sub is None:
                    raise HTTPException(status_code=409, detail="Org sem assinatura para alterar plano.")
                sub.plan_id = body.plan_id
    return await _get_org_out(org_id)


@router.post("/orgs/{org_id}/suspend", response_model=OrgOut)
async def suspend_org(org_id: int, _admin: PlatformAdminId) -> OrgOut:
    await _set_org_deleted(org_id, suspend=True)
    return await _get_org_out(org_id)


@router.post("/orgs/{org_id}/reactivate", response_model=OrgOut)
async def reactivate_org(org_id: int, _admin: PlatformAdminId) -> OrgOut:
    await _set_org_deleted(org_id, suspend=False)
    return await _get_org_out(org_id)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(_admin: PlatformAdminId, db: PlatformDB) -> DashboardOut:
    orgs = await platform_svc.list_orgs(db)
    suspended = sum(1 for o in orgs if o.get("deleted_at") is not None)
    active = sum(
        1 for o in orgs if o.get("deleted_at") is None and o.get("sub_status") == "active"
    )
    trial = sum(
        1 for o in orgs if o.get("deleted_at") is None and o.get("sub_status") == "trial"
    )
    usage_rows = await platform_svc.usage(db)

    # MRR consolidado: reusa mrr() (sob RLS por org) em sessão helper isolada —
    # o request nunca seta o GUC.
    ids = await platform_svc.active_org_ids(db)
    total_mrr = 0.0
    active_subs = 0
    async with AsyncSessionLocal() as helper:
        for oid in ids:
            async with helper.begin():
                await set_current_org(helper, oid)
                m = await mrr(helper)
            total_mrr += m["mrr"]
            active_subs += m["active_count"]

    return DashboardOut(
        counts=DashboardCountsOut(
            total=len(orgs), active=active, trial=trial, suspended=suspended
        ),
        mrr_consolidated=round(total_mrr, 2),
        active_subscriptions=active_subs,
        usage=[UsageOut(**u) for u in usage_rows],
    )


# ─── helpers de escrita escopada ───────────────────────────────────────────────

async def _set_org_deleted(org_id: int, *, suspend: bool) -> None:
    value = "now()" if suspend else "NULL"
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            org = (
                await session.execute(select(Organization).where(Organization.id == org_id))
            ).scalar_one_or_none()
            if org is None:
                raise HTTPException(status_code=404, detail="Org não encontrada.")
            await session.execute(
                text(f"UPDATE organizations SET deleted_at = {value} WHERE id = :id"),
                {"id": org_id},
            )


async def _get_org_out(org_id: int) -> OrgOut:
    """Releitura da org (via SECURITY DEFINER, enxerga inclusive suspensa)."""
    async with AsyncSessionLocal() as session:
        rows = await platform_svc.list_orgs(session)
    row = next((r for r in rows if r["id"] == org_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Org não encontrada.")
    return OrgOut(
        id=row["id"],
        name=row["name"],
        subdomain=row["subdomain"],
        plan_name=row["plan_name"],
        status=_derive_status(row),
        created_at=row["created_at"],
        deleted_at=row["deleted_at"],
    )
