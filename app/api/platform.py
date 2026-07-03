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
from datetime import date, datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_impersonation_token,
    create_platform_token,
    decode_access_token,
    verify_password,
)
from app.db.session import AsyncSessionLocal, get_db, set_current_org
from app.services import onboarding as onboarding_svc
from app.services import onboarding_progress as onb_progress
from app.services import platform as platform_svc
from app.services.management import mrr
from models import Organization, Plan, Subscription, WebhookEvent

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


class OrgOverviewOut(BaseModel):
    """Linha da tabela de gestão de barbearias (visão rica por org)."""

    id: int
    name: str
    subdomain: Optional[str] = None
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    plan_price_month: Optional[float] = None
    status: str  # derivado (mesma regra de OrgOut)
    sub_period_end: Optional[datetime] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    users_count: int
    barbers_count: int
    clients_count: int
    appt_30d: int
    last_activity: Optional[datetime] = None


# Ordenações aceitas em /orgs/overview. Datas ausentes ordenam como "mais antigas"
# (sentinela tz-aware — colunas do banco são timestamptz).
_DT_MIN = datetime(1, 1, 1, tzinfo=timezone.utc)
_ORG_ORDERS = ("name", "-name", "created_at", "-created_at", "last_activity", "-last_activity")


def _sort_org_overview(items: list["OrgOverviewOut"], order: str) -> list["OrgOverviewOut"]:
    field = order.lstrip("-")
    if field == "name":
        def key(o: "OrgOverviewOut"):
            return (o.name or "").lower()
    elif field == "created_at":
        def key(o: "OrgOverviewOut"):
            return o.created_at or _DT_MIN
    else:  # last_activity
        def key(o: "OrgOverviewOut"):
            return o.last_activity or _DT_MIN
    return sorted(items, key=key, reverse=order.startswith("-"))


class OrgsOverviewPageOut(BaseModel):
    items: list[OrgOverviewOut]
    total: int  # total APÓS filtros (para paginação)
    page: int
    per_page: int
    # Contagem por status derivado sobre TODAS as orgs (pré-filtro) — alimenta
    # as views salvas ("Ativas", "Trial", "Inadimplentes"...) sem outra chamada.
    counts: dict[str, int]


class OrgSubscriptionOut(BaseModel):
    id: int
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    plan_price_month: Optional[float] = None
    status: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class OrgUserOut(BaseModel):
    id: int
    email: str
    phone_e164: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    # Papel de MAIOR prioridade (owner > manager > reception > barber) + todos.
    role: Optional[str] = None
    roles: list[str] = []


class OrgBarberOut(BaseModel):
    id: int
    name: str
    specialty: Optional[str] = None
    work_model: Optional[str] = None
    commission_pct: Optional[float] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class OrgDetailOut(BaseModel):
    """Visão 360° de uma barbearia para o painel de plataforma."""

    id: int
    public_id: str
    name: str
    subdomain: Optional[str] = None
    wa_instance_name: Optional[str] = None
    legal_name: Optional[str] = None
    cnpj: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    instagram: Optional[str] = None
    logo_url: Optional[str] = None
    monthly_revenue_goal: Optional[float] = None
    status: str
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    subscription: Optional[OrgSubscriptionOut] = None
    plan_max_units: Optional[int] = None
    plan_max_barbers: Optional[int] = None
    # Indicadores de uso (mesma fonte da tabela de gestão).
    users_count: int = 0
    barbers_count: int = 0
    clients_count: int = 0
    appt_30d: int = 0
    last_activity: Optional[datetime] = None


class OrgNoteIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class OrgNoteOut(BaseModel):
    id: int
    admin_id: int
    admin_email: str
    body: str
    created_at: datetime


class TimelineEventOut(BaseModel):
    """Evento da linha do tempo unificada da org (mais recente primeiro)."""

    at: datetime
    kind: str  # 'org_created' | 'subscription_started' | 'subscription_canceled' | 'note'
    title: str
    detail: Optional[str] = None
    actor: Optional[str] = None


_ROLE_PRIORITY = ("owner", "manager", "reception", "barber")


def _highest_role(roles: Optional[list[str]]) -> Optional[str]:
    if not roles:
        return None
    for role in _ROLE_PRIORITY:
        if role in roles:
            return role
    return roles[0]


class OnboardingStageOut(BaseModel):
    key: str
    label: str
    done: bool
    source: str  # 'auto' (derivado dos dados) | 'manual' (override do superadmin)
    derivable: bool  # False = etapa sem sinal no sistema (só manual)


class OrgOnboardingOut(BaseModel):
    org_id: int
    items: list[OnboardingStageOut]
    progress_done: int
    progress_total: int


class OnboardingStageToggleIn(BaseModel):
    done: bool


class OnboardingFunnelStageOut(BaseModel):
    key: str
    label: str
    count: int  # orgs ativas com a etapa concluída


class OnboardingOrgRowOut(BaseModel):
    org_id: int
    name: str
    sub_status: Optional[str] = None
    trial_days_left: Optional[int] = None
    progress_done: int
    progress_total: int
    current_stage_key: Optional[str] = None
    current_stage_label: Optional[str] = None
    stuck_days: int
    last_activity: Optional[datetime] = None


class OnboardingOverviewOut(BaseModel):
    total_orgs: int
    completed_orgs: int
    funnel: list[OnboardingFunnelStageOut]
    # Em andamento, mais paradas primeiro; completas não entram na lista.
    orgs: list[OnboardingOrgRowOut]


class MetricsPointOut(BaseModel):
    """Um mês da série de crescimento do SaaS."""

    month: date
    new_orgs: int
    canceled_subs: int
    active_subs: int
    trial_subs: int
    mrr: float


class MetricsOut(BaseModel):
    """Métricas executivas do SaaS (visão do dono da plataforma).

    Até o billing real (invoices, M7) existir, MRR/série são derivados da
    vigência das assinaturas + preço do plano — mesma base do `saas_mrr` do
    dashboard. `churn_rate` é fração mensal (0.02 = 2%) do último mês fechado.
    """

    mrr: float
    arr: float
    # Ticket médio por assinatura ativa (ARPU). None sem assinaturas ativas.
    arpu: Optional[float] = None
    # Churn mensal do último mês fechado: canceladas / base ativa no início.
    churn_rate: Optional[float] = None
    # LTV estimado = ARPU / churn. None quando churn é 0/indefinido.
    ltv: Optional[float] = None
    # Contagem por status derivado (active/trial/past_due/canceled/suspended/sem_assinatura).
    counts: dict[str, int]
    series: list[MetricsPointOut]


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
async def suspend_org(org_id: int, admin_id: PlatformAdminId, db: PlatformDB) -> OrgOut:
    await _set_org_deleted(org_id, suspend=True)
    await platform_svc.audit_add(
        db, admin_id, action="org_suspended", category="org",
        target_type="organization", target_id=org_id, org_id=org_id,
    )
    return await _get_org_out(org_id)


@router.post("/orgs/{org_id}/reactivate", response_model=OrgOut)
async def reactivate_org(org_id: int, admin_id: PlatformAdminId, db: PlatformDB) -> OrgOut:
    await _set_org_deleted(org_id, suspend=False)
    await platform_svc.audit_add(
        db, admin_id, action="org_reactivated", category="org",
        target_type="organization", target_id=org_id, org_id=org_id,
    )
    return await _get_org_out(org_id)


@router.get("/orgs/overview", response_model=OrgsOverviewPageOut)
async def orgs_overview(
    _admin: PlatformAdminId,
    db: PlatformDB,
    q: Annotated[Optional[str], Query(max_length=120)] = None,
    org_status: Annotated[
        Optional[str], Query(alias="status", max_length=30)
    ] = None,
    plan_id: Annotated[Optional[int], Query(gt=0)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 25,
    order: Annotated[Literal[_ORG_ORDERS], Query()] = "name",  # type: ignore[valid-type]
) -> OrgsOverviewPageOut:
    """Tabela de gestão de barbearias: visão rica + busca + filtros + paginação.

    Filtros/ordenação/paginação em Python sobre o resultado da função
    SECURITY DEFINER — a base é de dezenas/centenas de orgs; quando crescer,
    empurrar para SQL (mesma decisão do loop de MRR do dashboard).

    NB de roteamento: declarado ANTES de qualquer rota GET `/orgs/{org_id}`
    (senão "overview" tentaria virar int e retornaria 422).
    """
    rows = await platform_svc.org_overview(db)
    all_items = [
        OrgOverviewOut(
            id=r["id"],
            name=r["name"],
            subdomain=r["subdomain"],
            plan_id=r["plan_id"],
            plan_name=r["plan_name"],
            plan_price_month=(
                float(r["plan_price_month"]) if r["plan_price_month"] is not None else None
            ),
            status=_derive_status(r),
            sub_period_end=r["sub_period_end"],
            created_at=r["created_at"],
            deleted_at=r["deleted_at"],
            users_count=r["users_count"],
            barbers_count=r["barbers_count"],
            clients_count=r["clients_count"],
            appt_30d=r["appt_30d"],
            last_activity=r["last_activity"],
        )
        for r in rows
    ]

    counts = Counter(o.status for o in all_items)

    filtered = all_items
    if q:
        needle = q.strip().lower()
        filtered = [
            o
            for o in filtered
            if needle in o.name.lower()
            or (o.subdomain and needle in o.subdomain.lower())
            or needle == str(o.id)
        ]
    if org_status:
        filtered = [o for o in filtered if o.status == org_status]
    if plan_id is not None:
        filtered = [o for o in filtered if o.plan_id == plan_id]

    filtered = _sort_org_overview(filtered, order)

    start = (page - 1) * per_page
    return OrgsOverviewPageOut(
        items=filtered[start : start + per_page],
        total=len(filtered),
        page=page,
        per_page=per_page,
        counts=dict(counts),
    )


# ─── onboarding (funil agregado) ───────────────────────────────────────────────
# NB: /onboarding é rota própria (não colide com /orgs/{org_id}).


@router.get("/onboarding", response_model=OnboardingOverviewOut)
async def onboarding_overview(_admin: PlatformAdminId, db: PlatformDB) -> OnboardingOverviewOut:
    """Funil de ativação de todas as orgs ativas + fila de onboardings em andamento."""
    signals = await platform_svc.onboarding_signals(db)
    overrides = await platform_svc.onboarding_overrides(db)

    funnel_counts: Counter[str] = Counter()
    rows: list[OnboardingOrgRowOut] = []
    completed = 0

    for s in signals:
        items = onb_progress.compute_checklist(s, overrides.get(s["org_id"], {}))
        done_count = sum(1 for i in items if i["done"])
        for i in items:
            if i["done"]:
                funnel_counts[i["key"]] += 1
        if done_count == len(items):
            completed += 1
            continue
        cur = onb_progress.current_stage(items)
        rows.append(
            OnboardingOrgRowOut(
                org_id=s["org_id"],
                name=s["name"],
                sub_status=s["sub_status"],
                trial_days_left=onb_progress.trial_days_left(s),
                progress_done=done_count,
                progress_total=len(items),
                current_stage_key=cur["key"] if cur else None,
                current_stage_label=cur["label"] if cur else None,
                stuck_days=onb_progress.stuck_days(s),
                last_activity=s["last_activity"],
            )
        )

    rows.sort(key=lambda r: r.stuck_days, reverse=True)
    return OnboardingOverviewOut(
        total_orgs=len(signals),
        completed_orgs=completed,
        funnel=[
            OnboardingFunnelStageOut(
                key=key, label=label, count=funnel_counts.get(key, 0)
            )
            for key, label in onb_progress.STAGES
        ],
        orgs=rows,
    )


def _org_signals_or_404(signals: list[dict], org_id: int) -> dict:
    row = next((s for s in signals if s["org_id"] == org_id), None)
    if row is None:
        # Org inexistente OU suspensa (sinais cobrem só ativas) — o detalhe da
        # org suspensa mostra o aviso de suspensão, não o onboarding.
        raise HTTPException(status_code=404, detail="Org não encontrada ou suspensa.")
    return row


def _checklist_out(org_id: int, signals: dict, overrides: dict[str, bool]) -> OrgOnboardingOut:
    items = onb_progress.compute_checklist(signals, overrides)
    return OrgOnboardingOut(
        org_id=org_id,
        items=[OnboardingStageOut(**i) for i in items],
        progress_done=sum(1 for i in items if i["done"]),
        progress_total=len(items),
    )


@router.get("/orgs/{org_id}/onboarding", response_model=OrgOnboardingOut)
async def org_onboarding(
    org_id: int, _admin: PlatformAdminId, db: PlatformDB
) -> OrgOnboardingOut:
    signals = _org_signals_or_404(await platform_svc.onboarding_signals(db), org_id)
    overrides = (await platform_svc.onboarding_overrides(db)).get(org_id, {})
    return _checklist_out(org_id, signals, overrides)


@router.put("/orgs/{org_id}/onboarding/{stage_key}", response_model=OrgOnboardingOut)
async def org_onboarding_set(
    org_id: int,
    stage_key: str,
    body: OnboardingStageToggleIn,
    admin_id: PlatformAdminId,
    db: PlatformDB,
) -> OrgOnboardingOut:
    """Marca/desmarca etapa manualmente (override vence a derivação automática)."""
    if stage_key not in onb_progress.STAGE_KEYS:
        raise HTTPException(status_code=422, detail="Etapa de onboarding desconhecida.")
    signals = _org_signals_or_404(await platform_svc.onboarding_signals(db), org_id)
    row = await platform_svc.onboarding_override_set(
        db, org_id, stage_key, body.done, admin_id
    )
    if row is None:
        raise HTTPException(status_code=403, detail="Superadmin não encontrado.")
    overrides = (await platform_svc.onboarding_overrides(db)).get(org_id, {})
    return _checklist_out(org_id, signals, overrides)


@router.delete("/orgs/{org_id}/onboarding/{stage_key}", response_model=OrgOnboardingOut)
async def org_onboarding_clear(
    org_id: int,
    stage_key: str,
    _admin: PlatformAdminId,
    db: PlatformDB,
) -> OrgOnboardingOut:
    """Remove o override manual — a etapa volta a refletir a derivação automática."""
    if stage_key not in onb_progress.STAGE_KEYS:
        raise HTTPException(status_code=422, detail="Etapa de onboarding desconhecida.")
    signals = _org_signals_or_404(await platform_svc.onboarding_signals(db), org_id)
    await platform_svc.onboarding_override_clear(db, org_id, stage_key)
    overrides = (await platform_svc.onboarding_overrides(db)).get(org_id, {})
    return _checklist_out(org_id, signals, overrides)


# NB: rotas GET /orgs/{org_id}/* vêm DEPOIS de /orgs/overview no arquivo — a
# ordem de declaração garante que "overview" não seja interpretado como org_id.


async def _org_profile_or_404(db: AsyncSession, org_id: int) -> dict:
    profile = await platform_svc.org_profile(db, org_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Org não encontrada.")
    return profile


@router.get("/orgs/{org_id}", response_model=OrgDetailOut)
async def org_detail(org_id: int, _admin: PlatformAdminId, db: PlatformDB) -> OrgDetailOut:
    """Visão 360° da barbearia: cadastro, assinatura vigente, plano e uso."""
    p = await _org_profile_or_404(db, org_id)

    # Indicadores de uso — mesma fonte da tabela (linha desta org).
    overview_rows = await platform_svc.org_overview(db)
    usage = next((r for r in overview_rows if r["id"] == org_id), {})

    subscription = (
        OrgSubscriptionOut(
            id=p["sub_id"],
            plan_id=p["plan_id"],
            plan_name=p["plan_name"],
            plan_price_month=(
                float(p["plan_price_month"]) if p["plan_price_month"] is not None else None
            ),
            status=p["sub_status"],
            current_period_start=p["sub_period_start"],
            current_period_end=p["sub_period_end"],
            canceled_at=p["sub_canceled_at"],
        )
        if p["sub_id"] is not None
        else None
    )

    return OrgDetailOut(
        id=p["id"],
        public_id=str(p["public_id"]),
        name=p["name"],
        subdomain=p["subdomain"],
        wa_instance_name=p["wa_instance_name"],
        legal_name=p["legal_name"],
        cnpj=p["cnpj"],
        phone=p["phone"],
        email=p["email"],
        website=p["website"],
        instagram=p["instagram"],
        logo_url=p["logo_url"],
        monthly_revenue_goal=(
            float(p["monthly_revenue_goal"]) if p["monthly_revenue_goal"] is not None else None
        ),
        status=_derive_status({"deleted_at": p["deleted_at"], "sub_status": p["sub_status"]}),
        created_at=p["created_at"],
        deleted_at=p["deleted_at"],
        subscription=subscription,
        plan_max_units=p["plan_max_units"],
        plan_max_barbers=p["plan_max_barbers"],
        users_count=usage.get("users_count", 0),
        barbers_count=usage.get("barbers_count", 0),
        clients_count=usage.get("clients_count", 0),
        appt_30d=usage.get("appt_30d", 0),
        last_activity=usage.get("last_activity"),
    )


@router.get("/orgs/{org_id}/users", response_model=list[OrgUserOut])
async def org_users(org_id: int, _admin: PlatformAdminId, db: PlatformDB) -> list[OrgUserOut]:
    await _org_profile_or_404(db, org_id)
    rows = await platform_svc.org_users(db, org_id)
    return [
        OrgUserOut(
            id=r["id"],
            email=r["email"],
            phone_e164=r["phone_e164"],
            is_active=r["is_active"],
            created_at=r["created_at"],
            role=_highest_role(r["roles"]),
            roles=r["roles"] or [],
        )
        for r in rows
    ]


@router.get("/orgs/{org_id}/barbers", response_model=list[OrgBarberOut])
async def org_barbers(org_id: int, _admin: PlatformAdminId, db: PlatformDB) -> list[OrgBarberOut]:
    await _org_profile_or_404(db, org_id)
    rows = await platform_svc.org_barbers(db, org_id)
    return [
        OrgBarberOut(
            id=r["id"],
            name=r["name"],
            specialty=r["specialty"],
            work_model=r["work_model"],
            commission_pct=(
                float(r["commission_pct"]) if r["commission_pct"] is not None else None
            ),
            created_at=r["created_at"],
            deleted_at=r["deleted_at"],
        )
        for r in rows
    ]


@router.get("/orgs/{org_id}/subscriptions", response_model=list[OrgSubscriptionOut])
async def org_subscriptions(
    org_id: int, _admin: PlatformAdminId, db: PlatformDB
) -> list[OrgSubscriptionOut]:
    await _org_profile_or_404(db, org_id)
    rows = await platform_svc.org_subscriptions(db, org_id)
    return [
        OrgSubscriptionOut(
            id=r["id"],
            plan_id=r["plan_id"],
            plan_name=r["plan_name"],
            plan_price_month=(
                float(r["plan_price_month"]) if r["plan_price_month"] is not None else None
            ),
            status=r["status"],
            current_period_start=r["current_period_start"],
            current_period_end=r["current_period_end"],
            canceled_at=r["canceled_at"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/orgs/{org_id}/notes", response_model=list[OrgNoteOut])
async def org_notes(org_id: int, _admin: PlatformAdminId, db: PlatformDB) -> list[OrgNoteOut]:
    await _org_profile_or_404(db, org_id)
    rows = await platform_svc.org_notes_list(db, org_id)
    return [OrgNoteOut(**r) for r in rows]


@router.post("/orgs/{org_id}/notes", response_model=OrgNoteOut, status_code=status.HTTP_201_CREATED)
async def org_note_add(
    org_id: int, body: OrgNoteIn, admin_id: PlatformAdminId, db: PlatformDB
) -> OrgNoteOut:
    """Registra observação interna/interação de suporte (invisível ao tenant)."""
    await _org_profile_or_404(db, org_id)
    row = await platform_svc.org_note_add(db, org_id, admin_id, body.body.strip())
    if row is None:
        # Guard já validou o admin; aqui só se ele sumiu entre as duas chamadas.
        raise HTTPException(status_code=403, detail="Superadmin não encontrado.")
    return OrgNoteOut(**row)


@router.get("/orgs/{org_id}/timeline", response_model=list[TimelineEventOut])
async def org_timeline(
    org_id: int, _admin: PlatformAdminId, db: PlatformDB
) -> list[TimelineEventOut]:
    """Linha do tempo unificada: cadastro, assinaturas e notas internas.

    Eventos de billing (faturas/pagamentos) e auditoria (impersonação etc.)
    entram nesta mesma lista quando M7/M9/M10 chegarem — o contrato já é o final.
    """
    p = await _org_profile_or_404(db, org_id)
    events: list[TimelineEventOut] = []

    if p["created_at"] is not None:
        events.append(
            TimelineEventOut(
                at=p["created_at"],
                kind="org_created",
                title="Conta criada na plataforma",
            )
        )

    for s in await platform_svc.org_subscriptions(db, org_id):
        if s["created_at"] is not None:
            plano = s["plan_name"] or f"plano #{s['plan_id']}"
            events.append(
                TimelineEventOut(
                    at=s["created_at"],
                    kind="subscription_started",
                    title=f"Assinatura iniciada — {plano}",
                    detail=f"status inicial: {s['status']}",
                )
            )
        if s["canceled_at"] is not None:
            events.append(
                TimelineEventOut(
                    at=s["canceled_at"],
                    kind="subscription_canceled",
                    title="Assinatura cancelada",
                    detail=s["plan_name"],
                )
            )

    for n in await platform_svc.org_notes_list(db, org_id):
        events.append(
            TimelineEventOut(
                at=n["created_at"],
                kind="note",
                title="Nota interna",
                detail=n["body"],
                actor=n["admin_email"],
            )
        )

    events.sort(key=lambda e: e.at, reverse=True)
    return events


# ─── impersonação (M10) ──────────────────────────────────────────────────────

class ImpersonateIn(BaseModel):
    # Motivo OBRIGATÓRIO — vai para o platform_audit_log, não para o token.
    reason: str = Field(..., min_length=5, max_length=300)
    minutes: int = Field(30, ge=5, le=60)


class ImpersonateOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    org_id: int
    org_name: str
    subdomain: Optional[str] = None
    impersonated_email: str  # owner da org cuja visão o token carrega


@router.post("/orgs/{org_id}/impersonate", response_model=ImpersonateOut)
async def impersonate_org(
    org_id: int, body: ImpersonateIn, admin_id: PlatformAdminId, db: PlatformDB
) -> ImpersonateOut:
    """Emite token de TENANT curto (5–60 min) como o OWNER da org, para suporte.

    Guarda-corpos: motivo obrigatório (auditado), expiração curta, claim
    `imp_by` no token, registro em `platform_audit_log` ANTES de devolver.
    Suspensa → 409 (reative primeiro; suspensão bloqueia o login normal e a
    impersonação não deve contorná-la silenciosamente).
    """
    profile = await _org_profile_or_404(db, org_id)
    if profile["deleted_at"] is not None:
        raise HTTPException(status_code=409, detail="Org suspensa — reative antes de impersonar.")

    users = await platform_svc.org_users(db, org_id)
    owner = next(
        (u for u in users if u["is_active"] and "owner" in (u["roles"] or [])), None
    )
    if owner is None:
        raise HTTPException(status_code=409, detail="Org sem owner ativo para impersonar.")

    await platform_svc.audit_add(
        db, admin_id, action="impersonation_started", category="impersonation",
        target_type="user", target_id=owner["id"], org_id=org_id,
        reason=body.reason, metadata={"minutes": body.minutes, "email": owner["email"]},
    )
    token = create_impersonation_token(
        user_id=owner["id"], organization_id=org_id,
        admin_id=admin_id, minutes=body.minutes,
    )
    return ImpersonateOut(
        access_token=token,
        expires_in_minutes=body.minutes,
        org_id=org_id,
        org_name=profile["name"],
        subdomain=profile["subdomain"],
        impersonated_email=owner["email"],
    )


# ─── central de operações / auditoria ────────────────────────────────────────

class AlertOut(BaseModel):
    severity: str  # critical | warning | info
    kind: str
    title: str
    detail: Optional[str] = None
    org_id: Optional[int] = None
    org_name: Optional[str] = None
    href: Optional[str] = None  # rota do painel para agir


class AlertsOut(BaseModel):
    counts: dict[str, int]  # severity → quantidade
    alerts: list[AlertOut]


_SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}


@router.get("/alerts", response_model=AlertsOut)
async def alerts(_admin: PlatformAdminId, db: PlatformDB) -> AlertsOut:
    """Central de Operações: alertas acionáveis derivados por regra.

    Regras (limiares documentados em decisions.md/SA-D10):
    cobrança em atraso (crítico) · webhooks de billing falhos (crítico) ·
    trial terminando ≤7d (aviso) · onboarding parado >7d (aviso) ·
    conta pagante sem atividade ≥30d (aviso).
    """
    out: list[AlertOut] = []

    billing_rows = await platform_svc.billing_subscriptions(db)
    for r in billing_rows:
        if r["org_deleted_at"] is not None:
            continue
        if (r["days_overdue"] or 0) > 0:
            out.append(AlertOut(
                severity="critical", kind="payment_overdue",
                title=f"Cobrança em atraso há {r['days_overdue']} dia(s)",
                detail=(
                    f"R$ {float(r['open_amount'] or 0):.2f} em aberto"
                    + (f" · última tentativa #{r['last_attempt']}" if r["last_attempt"] else "")
                ),
                org_id=r["org_id"], org_name=r["org_name"],
                href=f"/tenants/{r['org_id']}",
            ))

    signals = await platform_svc.onboarding_signals(db)
    overrides = await platform_svc.onboarding_overrides(db)
    for s in signals:
        items = onb_progress.compute_checklist(s, overrides.get(s["org_id"], {}))
        done = sum(1 for i in items if i["done"])
        trial_left = onb_progress.trial_days_left(s)
        stuck = onb_progress.stuck_days(s)
        if trial_left is not None and 0 <= trial_left <= 7:
            out.append(AlertOut(
                severity="warning", kind="trial_ending",
                title=f"Trial termina em {trial_left} dia(s)",
                detail=f"onboarding {done}/{len(items)} — hora de converter",
                org_id=s["org_id"], org_name=s["name"],
                href=f"/tenants/{s['org_id']}",
            ))
        if done < len(items) and stuck > 7:
            cur = onb_progress.current_stage(items)
            out.append(AlertOut(
                severity="warning", kind="onboarding_stuck",
                title=f"Onboarding parado há {stuck} dia(s)",
                detail=f"etapa atual: {cur['label'] if cur else '—'}",
                org_id=s["org_id"], org_name=s["name"],
                href=f"/tenants/{s['org_id']}",
            ))
        elif done == len(items) and stuck >= 30 and s["sub_status"] in ("active", "past_due"):
            out.append(AlertOut(
                severity="warning", kind="inactive_account",
                title=f"Sem atividade há {stuck} dia(s)",
                detail="conta pagante sem agendamentos/mensagens — risco de churn",
                org_id=s["org_id"], org_name=s["name"],
                href=f"/tenants/{s['org_id']}",
            ))

    failed_webhooks = (
        await db.execute(
            select(func.count()).select_from(WebhookEvent).where(WebhookEvent.status == "failed")
        )
    ).scalar_one()
    if failed_webhooks:
        out.append(AlertOut(
            severity="critical", kind="webhook_failures",
            title=f"{failed_webhooks} webhook(s) de billing falharam",
            detail="reprocesse na tela de logs ou investigue o gateway",
            href="/logs",
        ))

    out.sort(key=lambda a: _SEV_ORDER.get(a.severity, 9))
    counts = Counter(a.severity for a in out)
    return AlertsOut(counts=dict(counts), alerts=out)


class AuditLogRowOut(BaseModel):
    id: int
    admin_email: str
    action: str
    category: str
    target_type: str
    target_id: Optional[int] = None
    organization_id: Optional[int] = None
    reason: Optional[str] = None
    metadata: dict = {}
    ip: Optional[str] = None
    created_at: datetime


@router.get("/audit-log", response_model=list[AuditLogRowOut])
async def audit_log(
    _admin: PlatformAdminId,
    db: PlatformDB,
    category: Annotated[Optional[str], Query(max_length=30)] = None,
    org_id: Annotated[Optional[int], Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditLogRowOut]:
    rows = await platform_svc.audit_list(db, limit=limit, category=category, org_id=org_id)
    return [AuditLogRowOut(**r) for r in rows]


@router.get("/metrics", response_model=MetricsOut)
async def metrics(
    _admin: PlatformAdminId,
    db: PlatformDB,
    months: Annotated[int, Query(ge=1, le=36)] = 12,
) -> MetricsOut:
    """Métricas executivas: MRR, ARR, ARPU, churn, LTV e série mensal."""
    orgs = await platform_svc.list_orgs(db)
    status_counts = Counter(_derive_status(o) for o in orgs)

    # Mesma regra do dashboard (fonte única de MRR atual do SaaS).
    mrr_now = sum(
        float(o["plan_price_month"] or 0)
        for o in orgs
        if o.get("deleted_at") is None and o.get("sub_status") == "active"
    )
    active_now = status_counts.get("active", 0)
    arpu = round(mrr_now / active_now, 2) if active_now else None

    series_rows = await platform_svc.metrics_monthly(db, months)
    series = [
        MetricsPointOut(
            month=r["month"],
            new_orgs=r["new_orgs"],
            canceled_subs=r["canceled_subs"],
            active_subs=r["active_subs"],
            trial_subs=r["trial_subs"],
            mrr=float(r["mrr"] or 0),
        )
        for r in series_rows
    ]

    # Churn do último mês FECHADO (o último ponto é o mês corrente, parcial):
    # cancelados em M ÷ base ativa ao fim de M-1. Precisa de pelo menos 3 pontos.
    churn: Optional[float] = None
    if len(series) >= 3:
        closed = series[-2]
        base = series[-3].active_subs
        if base > 0:
            churn = round(closed.canceled_subs / base, 4)

    ltv: Optional[float] = None
    if arpu is not None and churn is not None and churn > 0:
        ltv = round(arpu / churn, 2)

    return MetricsOut(
        mrr=round(mrr_now, 2),
        arr=round(mrr_now * 12, 2),
        arpu=arpu,
        churn_rate=churn,
        ltv=ltv,
        counts=dict(status_counts),
        series=series,
    )


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
