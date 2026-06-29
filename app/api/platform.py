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

import logging
from collections import Counter
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
from models import Organization, Plan, Subscription

_logger = logging.getLogger(__name__)
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
    # MRR do SaaS: soma de Plan.price_month das assinaturas ATIVAS dos tenants —
    # a receita recorrente que as barbearias pagam à plataforma.
    saas_mrr: float
    # MRR agregado das mensalidades dos CLIENTES FINAIS (soma de mrr() por org).
    # NÃO é receita do SaaS — é o volume recorrente que passa pelos tenants.
    tenants_membership_mrr: float
    tenants_active_memberships: int
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
    except IntegrityError:
        # Conflito de dados esperado (subdomínio já em uso, plano inexistente/FK).
        # Não vaza detalhe interno; demais erros propagam como 500 (bug real).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível criar a org: subdomínio já em uso ou plano inválido.",
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
                # Valida o plano ANTES de atribuir, senão a FK estoura no commit
                # como 500 não tratado. `plans` é catálogo global (sem RLS).
                plan_exists = (
                    await session.execute(
                        select(Plan.id).where(Plan.id == body.plan_id)
                    )
                ).scalar_one_or_none()
                if plan_exists is None:
                    raise HTTPException(status_code=400, detail="Plano inexistente.")
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
    # Contagens derivadas da MESMA regra de status da listagem (fonte única).
    status_counts = Counter(_derive_status(o) for o in orgs)

    # MRR do SaaS: soma do preço do plano das assinaturas ativas (não suspensas).
    saas_mrr = sum(
        float(o["plan_price_month"] or 0)
        for o in orgs
        if o.get("deleted_at") is None and o.get("sub_status") == "active"
    )

    usage_rows = await platform_svc.usage(db)

    # MRR agregado das mensalidades dos clientes finais: reusa mrr() (sob RLS por
    # org) em sessão helper isolada — o request nunca seta o GUC. Uma org com dado
    # inconsistente não pode derrubar o painel inteiro: isola por org.
    # NB: O(N) round-trips — débito de escala conhecido (paginar/agregar via função
    # SECURITY DEFINER quando a base crescer).
    ids = await platform_svc.active_org_ids(db)
    tenants_mrr = 0.0
    tenants_memberships = 0
    async with AsyncSessionLocal() as helper:
        for oid in ids:
            try:
                async with helper.begin():
                    await set_current_org(helper, oid)
                    m = await mrr(helper)
                tenants_mrr += m["mrr"]
                tenants_memberships += m["active_count"]
            except Exception as exc:  # noqa: BLE001 — um tenant ruim não derruba o painel
                _logger.warning("dashboard mrr falhou para org %s: %s", oid, exc)

    return DashboardOut(
        counts=DashboardCountsOut(
            total=len(orgs),
            active=status_counts.get("active", 0),
            trial=status_counts.get("trial", 0),
            suspended=status_counts.get("suspended", 0),
        ),
        saas_mrr=round(saas_mrr, 2),
        tenants_membership_mrr=round(tenants_mrr, 2),
        tenants_active_memberships=tenants_memberships,
        usage=[UsageOut(**u) for u in usage_rows],
    )


# ─── helpers de escrita escopada ───────────────────────────────────────────────

async def _set_org_deleted(org_id: int, *, suspend: bool) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, org_id)
            org = (
                await session.execute(select(Organization).where(Organization.id == org_id))
            ).scalar_one_or_none()
            if org is None:
                raise HTTPException(status_code=404, detail="Org não encontrada.")
            # ORM (sem f-string SQL): server-side now() na suspensão, NULL ao reativar.
            org.deleted_at = func.now() if suspend else None


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
