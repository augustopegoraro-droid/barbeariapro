# file: app/api/public.py
"""Site público de agendamento do cliente final (D-79).

Rotas SEM autenticação de staff, escopadas por subdomínio no path
(`/public/{subdomain}/...`): a org é resolvida via `app_org_id_by_subdomain`
(SECURITY DEFINER, molde `GET /auth/tenant`) e a sessão passa a operar sob
RLS normal — a RLS continua sendo a única barreira multi-tenant.

Autenticação do cliente final: cookie `tt_session` (token opaco de 256 bits,
só o hash persiste em `client_sessions`). v1 SEM OTP (WhatsApp restrito,
D-41): a sessão só enxerga os agendamentos que ela mesma criou
(`created_by_client_session_id`) — ver ARQUITETURA_SITE_PUBLICO.md §1.

A vitrine (`GET /info`) respeita exatamente o que o gestor configurou em
`client_visibility_settings` (D-73) e nunca expõe dado interno (comissão,
custo, telefone de outros clientes).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status as http_status,
)
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.phone import mask_phone, normalize_phone
from app.core.privacy import PRIVACY_POLICY_VERSION, SOURCE_SITE_SIGNUP
from app.core.rate_limit import limiter
from app.core.security import generate_refresh_token, hash_refresh_token
from app.db.redis import get_redis
from app.db.session import get_db, set_current_org
from app.services.audit import record_event
from app.services.availability import free_slots
from app.services.consent import set_consent
from app.services import media
from app.services.calendar_sync import push_appointment
from app.services import push as push_svc
from app.services.public_cache import (
    FEED_CACHE_TTL_SECONDS,
    INFO_CACHE_TTL_SECONDS,
    PLANS_CACHE_TTL_SECONDS,
    feed_cache_key,
    info_cache_key,
    plans_cache_key,
)
from app.services.connect import service as connect_svc
from app.services.connect.provider import ConnectProviderError
from app.services.connect.registry import get_connect_provider
from app.services import membership as membership_svc
from app.services.scheduling import barber_has_conflict
from app.services.tenant import org_id_by_subdomain
from models import (
    Appointment,
    AppointmentItem,
    AppointmentRating,
    AppointmentStatus,
    Barber,
    BarberService,
    BusinessHours,
    Client,
    ClientConsent,
    ClientSession,
    ClientVisibilitySettings,
    ConsentStatus,
    ContactChannel,
    FeedPost,
    MembershipOrder,
    MembershipPlan,
    MembershipPlanItem,
    Organization,
    PushChannel,
    PushSubscriberType,
    PushSubscription,
    Service,
    Unit,
)

router = APIRouter(prefix="/public/{subdomain}", tags=["public"])
logger = logging.getLogger(__name__)

SESSION_COOKIE = "tt_session"

FEED_DEFAULT_LIMIT = 10
FEED_MAX_LIMIT = 30


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ─── dependencies ────────────────────────────────────────────────────────────

async def get_public_org(
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> int:
    """Resolve a org pelo subdomínio do path e escopa a sessão (RLS)."""
    org_id = await org_id_by_subdomain(db, subdomain)
    if org_id is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Estabelecimento não encontrado.")
    await set_current_org(db, org_id)
    return org_id


async def get_client_session(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
) -> ClientSession:
    """Autentica pelo cookie de sessão do cliente final (sob RLS da org)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(http_status.HTTP_401_UNAUTHORIZED, "Sessão ausente.")
    row = (
        await db.execute(
            select(ClientSession)
            .where(ClientSession.token_hash == hash_refresh_token(token))
            .where(ClientSession.revoked_at.is_(None))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(http_status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada.")
    row.last_seen_at = datetime.now(timezone.utc)
    return row


async def _default_unit(db: AsyncSession, org_id: int) -> Unit:
    unit = (
        await db.execute(
            select(Unit)
            .where(Unit.organization_id == org_id)
            .where(Unit.deleted_at.is_(None))
            .order_by(Unit.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not unit:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Estabelecimento sem unidade configurada.")
    return unit


def _visible_ids(selection: Optional[dict]) -> Optional[set[int]]:
    """None = todos visíveis; set = só estes ids (mode custom)."""
    if not selection or selection.get("mode") != "custom":
        return None
    return {int(i) for i in selection.get("ids", [])}


async def _visibility(db: AsyncSession, org_id: int) -> Optional[ClientVisibilitySettings]:
    return (
        await db.execute(
            select(ClientVisibilitySettings).where(
                ClientVisibilitySettings.organization_id == org_id
            )
        )
    ).scalar_one_or_none()


# ─── schemas ─────────────────────────────────────────────────────────────────

class PublicServiceOut(BaseModel):
    id: int
    name: str
    category: str
    duration_min: int
    price: float
    barber_ids: list[int]


class PublicProfessionalOut(BaseModel):
    id: int
    name: str
    specialty: Optional[str]
    photo_url: Optional[str] = None


class PublicHourOut(BaseModel):
    weekday: int  # 0=domingo ... 6=sábado
    open_time: str
    close_time: str


class PublicInfoOut(BaseModel):
    name: str
    services: list[PublicServiceOut]
    professionals: list[PublicProfessionalOut]
    hours: list[PublicHourOut]
    banner: dict
    public_info: dict


class FeedPostOut(BaseModel):
    id: str  # `public_id` (uuid) — o id sequencial não sai do painel
    title: str
    body: str
    image_url: Optional[str] = None
    published_at: datetime
    pinned: bool


class FeedOut(BaseModel):
    posts: list[FeedPostOut]


class SessionCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=25)
    # Aceite explícito da política de privacidade (LGPD, D-86). Obrigatório:
    # é aqui que o titular entra na base, então é aqui que a base legal nasce.
    accept_privacy: bool = Field(
        description="Aceite da política de privacidade — obrigatório para criar a sessão."
    )


class SessionOut(BaseModel):
    client_name: str
    is_new_client: bool


class SlotsOut(BaseModel):
    slots: list[str]  # ISO UTC


class BookIn(BaseModel):
    service_id: int
    barber_id: int
    start_at: datetime


class PublicAppointmentOut(BaseModel):
    public_id: str
    service_name: str
    barber_name: str
    # ids explícitos: destravam remarcação/reagendamento com pré-seleção no
    # frontend (que só recebia nomes e não conseguia montar o deep-link).
    service_id: int
    barber_id: int
    start_at: str
    end_at: str
    status: str
    total_amount: float
    cancelable: bool
    rating: Optional[int] = None
    can_rate: bool = False


def _cancelable(appt: Appointment, now: datetime) -> bool:
    return (
        appt.status == AppointmentStatus.agendado
        and appt.start_at > now + timedelta(hours=settings.public_cancel_min_hours)
    )


def _can_rate(appt: Appointment, rating: Optional[int], now: datetime) -> bool:
    """Concluído, ainda não avaliado e dentro da janela de avaliação."""
    return (
        rating is None
        and appt.status == AppointmentStatus.concluido
        and appt.end_at >= now - timedelta(days=settings.public_rating_window_days)
    )


def _appointment_out(
    appt: Appointment,
    item: AppointmentItem,
    service_name: str,
    barber_name: str,
    *,
    now: datetime,
    rating: Optional[int] = None,
) -> PublicAppointmentOut:
    return PublicAppointmentOut(
        public_id=str(appt.public_id),
        service_name=service_name,
        barber_name=barber_name,
        service_id=item.service_id,
        barber_id=item.barber_id,
        start_at=appt.start_at.isoformat(),
        end_at=appt.end_at.isoformat(),
        status=appt.status.value,
        total_amount=float(appt.total_amount),
        cancelable=_cancelable(appt, now),
        rating=rating,
        can_rate=_can_rate(appt, rating, now),
    )


# ─── GET /info ───────────────────────────────────────────────────────────────

@router.get("/info", response_model=PublicInfoOut)
@limiter.limit("60/minute")
async def public_info(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
) -> PublicInfoOut:
    cache_key = info_cache_key(org_id)
    try:
        cached = await get_redis().get(cache_key)
        if cached:
            return PublicInfoOut(**json.loads(cached))
    except Exception:
        pass  # cache é otimização; Redis fora não derruba a vitrine

    org_name = (
        await db.execute(select(Organization.name).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org_name is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Estabelecimento não encontrado.")

    vis = await _visibility(db, org_id)
    svc_ids = _visible_ids(vis.services if vis else None)
    pro_ids = _visible_ids(vis.professionals if vis else None)

    barbers = (
        (
            await db.execute(
                select(Barber).where(Barber.deleted_at.is_(None)).order_by(Barber.name)
            )
        )
        .scalars()
        .all()
    )
    if pro_ids is not None:
        barbers = [b for b in barbers if b.id in pro_ids]
    visible_barber_ids = {b.id for b in barbers}

    services = (
        (
            await db.execute(
                select(Service)
                .where(Service.is_active.is_(True))
                .where(Service.deleted_at.is_(None))
                .order_by(Service.name)
            )
        )
        .scalars()
        .all()
    )
    if svc_ids is not None:
        services = [s for s in services if s.id in svc_ids]

    links = (
        await db.execute(
            select(BarberService.service_id, BarberService.barber_id).where(
                BarberService.barber_id.in_(visible_barber_ids or {0})
            )
        )
    ).all()
    by_service: dict[int, list[int]] = {}
    for service_id, barber_id in links:
        by_service.setdefault(service_id, []).append(barber_id)

    hours: list[PublicHourOut] = []
    if vis is None or vis.show_hours:
        unit = await _default_unit(db, org_id)
        rows = (
            (
                await db.execute(
                    select(BusinessHours)
                    .where(BusinessHours.unit_id == unit.id)
                    .order_by(BusinessHours.weekday, BusinessHours.open_time)
                )
            )
            .scalars()
            .all()
        )
        hours = [
            PublicHourOut(
                weekday=h.weekday,
                open_time=h.open_time.strftime("%H:%M"),
                close_time=h.close_time.strftime("%H:%M"),
            )
            for h in rows
        ]

    out = PublicInfoOut(
        name=org_name,
        services=[
            PublicServiceOut(
                id=s.id,
                name=s.name,
                category=s.category.value,
                duration_min=s.default_duration_min,
                price=float(s.price),
                barber_ids=sorted(by_service.get(s.id, [])),
            )
            for s in services
            # serviço sem nenhum profissional visível não é agendável no site
            if by_service.get(s.id)
        ],
        professionals=[
            PublicProfessionalOut(
                id=b.id,
                name=b.name,
                specialty=b.specialty,
                photo_url=media.public_url(b.photo_path),
            )
            for b in barbers
        ],
        hours=hours,
        banner=(vis.banner if vis else {}) or {},
        public_info=(vis.public_info if vis else {}) or {},
    )
    try:
        await get_redis().setex(cache_key, INFO_CACHE_TTL_SECONDS, out.model_dump_json())
    except Exception:
        pass
    return out


# ─── GET /feed ───────────────────────────────────────────────────────────────

@router.get("/feed", response_model=FeedOut)
@limiter.limit("60/minute")
async def public_feed(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    limit: int = Query(FEED_DEFAULT_LIMIT, ge=1, le=FEED_MAX_LIMIT),
    before: Optional[datetime] = Query(
        None, description="Cursor: devolve só posts com `published_at` anterior a este."
    ),
) -> FeedOut:
    """Mural de novidades da barbearia. Público — não exige sessão de cliente.

    Paginação por **cursor** (`before`), não por offset: um post novo entrando
    no topo entre duas páginas não empurra itens para frente (o offset
    duplicaria/pularia). O cliente manda de volta o `published_at` do último
    item recebido.
    """
    is_first_page = before is None
    cache_key = feed_cache_key(org_id)
    if is_first_page and limit == FEED_DEFAULT_LIMIT:
        try:
            cached = await get_redis().get(cache_key)
            if cached:
                return FeedOut(**json.loads(cached))
        except Exception:
            pass  # cache é otimização; Redis fora não derruba o feed

    now = datetime.now(timezone.utc)
    stmt = (
        select(FeedPost)
        .where(FeedPost.is_published.is_(True))
        .where(FeedPost.deleted_at.is_(None))
        .where(FeedPost.published_at <= now)
        # `id DESC` desempata posts com o mesmo instante (import/seed em lote):
        # sem ele a ordem seria indefinida e a paginação poderia repetir itens.
        .order_by(FeedPost.pinned.desc(), FeedPost.published_at.desc(), FeedPost.id.desc())
        .limit(limit)
    )
    if before is not None:
        stmt = stmt.where(FeedPost.published_at < before)

    rows = (await db.execute(stmt)).scalars().all()
    out = FeedOut(
        posts=[
            FeedPostOut(
                id=str(p.public_id),
                title=p.title,
                body=p.body,
                image_url=media.public_url(p.image_path),
                published_at=p.published_at,
                pinned=p.pinned,
            )
            for p in rows
        ]
    )
    if is_first_page and limit == FEED_DEFAULT_LIMIT:
        try:
            await get_redis().setex(
                cache_key, FEED_CACHE_TTL_SECONDS, out.model_dump_json()
            )
        except Exception:
            pass
    return out


# ─── GET /slots ──────────────────────────────────────────────────────────────

@router.get("/slots", response_model=SlotsOut)
@limiter.limit("60/minute")
async def public_slots(
    request: Request,
    subdomain: str,
    service_id: int,
    barber_id: int,
    day: date,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
) -> SlotsOut:
    svc, barber = await _validate_service_barber(db, org_id, service_id, barber_id)
    unit = await _default_unit(db, org_id)
    slots = await free_slots(
        db, unit=unit, barber_id=barber.id, duration_minutes=svc.default_duration_min, day=day
    )
    return SlotsOut(slots=[s.isoformat() for s in slots])


async def _validate_service_barber(
    db: AsyncSession, org_id: int, service_id: int, barber_id: int
) -> tuple[Service, Barber]:
    """Serviço ativo + profissional ativo + vínculo + visibilidade do site."""
    svc = (
        await db.execute(select(Service).where(Service.id == service_id))
    ).scalar_one_or_none()
    if not svc or not svc.is_active or svc.deleted_at is not None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Serviço não encontrado.")
    barber = (
        await db.execute(select(Barber).where(Barber.id == barber_id))
    ).scalar_one_or_none()
    if not barber or barber.deleted_at is not None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Profissional não encontrado.")
    link = (
        await db.execute(
            select(BarberService)
            .where(BarberService.barber_id == barber_id)
            .where(BarberService.service_id == service_id)
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Este profissional não realiza este serviço.",
        )
    vis = await _visibility(db, org_id)
    svc_ids = _visible_ids(vis.services if vis else None)
    pro_ids = _visible_ids(vis.professionals if vis else None)
    if (svc_ids is not None and svc.id not in svc_ids) or (
        pro_ids is not None and barber.id not in pro_ids
    ):
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Serviço não encontrado.")
    return svc, barber


# ─── POST /auth/session ──────────────────────────────────────────────────────

@router.post("/auth/session", response_model=SessionOut, status_code=http_status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def create_session(
    body: SessionCreateIn,
    request: Request,
    response: Response,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
) -> SessionOut:
    if not body.accept_privacy:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "É necessário aceitar a política de privacidade para continuar.",
        )
    try:
        phone = normalize_phone(body.phone)
    except ValueError:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Telefone inválido.")

    client = (
        await db.execute(select(Client).where(Client.phone_e164 == phone))
    ).scalar_one_or_none()
    if client is not None and client.is_blocked:
        # Mensagem genérica: não confirmar que o telefone existe/está bloqueado.
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "Não foi possível iniciar a sessão.")

    is_new = client is None
    if is_new:
        client = Client(
            organization_id=org_id,
            name=body.name.strip(),
            phone_e164=phone,
            acquisition_channel=ContactChannel.site,
        )
        db.add(client)
        await db.flush()

    # Base legal do contato (D-86). Para quem já existia sem consentimento
    # registrado (ex.: carga histórica da Trinks), este aceite é o primeiro —
    # daí gravar também no caminho do cliente existente. Quem já tem estado
    # gravado (inclusive opt-out) não é tocado: aceitar a política do site não
    # pode ressuscitar um descadastro que o titular pediu no WhatsApp.
    has_consent = (
        await db.execute(
            select(ClientConsent.id)
            .where(ClientConsent.client_id == client.id)
            .where(ClientConsent.channel == ContactChannel.whatsapp)
            .limit(1)
        )
    ).scalar_one_or_none()
    if has_consent is None:
        await set_consent(
            db,
            organization_id=org_id,
            client_id=client.id,
            channel=ContactChannel.whatsapp,
            status=ConsentStatus.opt_in,
            source=SOURCE_SITE_SIGNUP,
            ip=_client_ip(request),
        )

    raw_token, token_hash = generate_refresh_token()
    session_row = ClientSession(
        organization_id=org_id,
        client_id=client.id,
        token_hash=token_hash,
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
        ip=_client_ip(request),
    )
    db.add(session_row)
    await db.flush()
    client_name = client.name
    client_id = client.id
    await db.commit()

    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=settings.public_session_max_age_days * 86400,
        domain=settings.public_cookie_domain or None,
        httponly=True,
        secure=bool(settings.public_cookie_domain),
        samesite="lax",
        path="/",
    )
    record_event(
        organization_id=org_id,
        action="public.session_created",
        actor_kind="client",
        resource_type="client",
        resource_id=client_id,
        reason=f"Aceite da política de privacidade v{PRIVACY_POLICY_VERSION}",
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SessionOut(client_name=client_name, is_new_client=is_new)


# ─── POST /appointments ──────────────────────────────────────────────────────

@router.post("/appointments", response_model=PublicAppointmentOut, status_code=http_status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def book_appointment(
    body: BookIn,
    request: Request,
    background_tasks: BackgroundTasks,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> PublicAppointmentOut:
    svc, barber = await _validate_service_barber(db, org_id, body.service_id, body.barber_id)
    appt, item = await _place_appointment(
        db, org_id=org_id, session=session, svc=svc, barber=barber, start_at=body.start_at
    )
    appt_id = appt.id
    start_iso = appt.start_at.isoformat()
    out = _appointment_out(
        appt, item, svc.name, barber.name, now=datetime.now(timezone.utc)
    )
    await db.commit()

    background_tasks.add_task(push_appointment, appt_id, org_id, "upsert")
    background_tasks.add_task(push_svc.notify_booking_confirmation, appt_id, org_id)
    record_event(
        organization_id=org_id,
        action="public.appointment_created",
        actor_kind="client",
        resource_type="appointment",
        resource_id=appt_id,
        after={"service_id": svc.id, "barber_id": barber.id, "start_at": start_iso},
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return out


async def _place_appointment(
    db: AsyncSession,
    *,
    org_id: int,
    session: ClientSession,
    svc: Service,
    barber: Barber,
    start_at: datetime,
) -> tuple[Appointment, AppointmentItem]:
    """Cria `Appointment` + `AppointmentItem` na transação corrente (SEM commit).

    Extraído de `book_appointment` para que a remarcação (que cancela o antigo
    e cria o novo) use exatamente a mesma validação de grade/conflito e o mesmo
    lock de numeração, na MESMA transação — nunca em duas chamadas.
    """
    if start_at.tzinfo is None:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "start_at deve incluir fuso horário.")
    start_utc = start_at.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=svc.default_duration_min)

    unit = await _default_unit(db, org_id)
    # O slot pedido precisa estar na grade oferecida (horário de funcionamento
    # + antecedência mínima + passo de 30min + sem conflito).
    day_local = start_utc.astimezone(ZoneInfo(unit.timezone)).date()
    offered = await free_slots(
        db, unit=unit, barber_id=barber.id, duration_minutes=svc.default_duration_min, day=day_local
    )
    if start_utc not in offered:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Este horário não está mais disponível.")

    # Revalida conflito imediatamente antes do insert (corrida entre clientes).
    if await barber_has_conflict(db, barber.id, start_utc, end_utc):
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Este horário não está mais disponível.")

    await db.execute(text("SELECT pg_advisory_xact_lock(:unit_id)"), {"unit_id": unit.id})
    next_num = (
        await db.execute(
            select(func.coalesce(func.max(Appointment.display_number), 0) + 1)
            .where(Appointment.unit_id == unit.id)
        )
    ).scalar_one()

    price = float(svc.price)  # site nunca altera preço (sem price_override)
    appt = Appointment(
        organization_id=org_id,
        unit_id=unit.id,
        client_id=session.client_id,
        display_number=next_num,
        start_at=start_utc,
        end_at=end_utc,
        status=AppointmentStatus.agendado,
        booking_channel=ContactChannel.site,
        total_amount=price,
        created_by_client_session_id=session.id,
    )
    db.add(appt)
    await db.flush()

    item = AppointmentItem(
        organization_id=org_id,
        appointment_id=appt.id,
        service_id=svc.id,
        barber_id=barber.id,
        price_charged=price,
        duration_minutes=svc.default_duration_min,
    )
    db.add(item)
    await db.flush()
    return appt, item


# ─── GET /me/appointments ────────────────────────────────────────────────────

@router.get("/me/appointments", response_model=list[PublicAppointmentOut])
@limiter.limit("60/minute")
async def my_appointments(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> list[PublicAppointmentOut]:
    rows = (
        await db.execute(
            select(Appointment, AppointmentItem, Service.name, Barber.name)
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .join(Service, Service.id == AppointmentItem.service_id)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .where(Appointment.created_by_client_session_id == session.id)
            .order_by(Appointment.start_at.desc())
            .limit(50)
        )
    ).all()
    now = datetime.now(timezone.utc)
    ratings = await _ratings_by_appointment(db, [appt.id for appt, *_ in rows])
    return [
        _appointment_out(
            appt, item, service_name, barber_name, now=now, rating=ratings.get(appt.id)
        )
        for appt, item, service_name, barber_name in rows
    ]


async def _ratings_by_appointment(
    db: AsyncSession, appointment_ids: list[int]
) -> dict[int, int]:
    if not appointment_ids:
        return {}
    rows = (
        await db.execute(
            select(AppointmentRating.appointment_id, AppointmentRating.rating).where(
                AppointmentRating.appointment_id.in_(appointment_ids)
            )
        )
    ).all()
    return {appointment_id: rating for appointment_id, rating in rows}


async def _load_own_appointment(
    db: AsyncSession, session: ClientSession, public_id: str
) -> tuple[Appointment, AppointmentItem, str, str]:
    """Agendamento DESTA sessão (D-79: sem OTP, cada sessão só vê o que criou).

    Fora da sessão → 404 (nunca 403): não confirmar que o agendamento existe.
    """
    try:
        appt_uuid = uuid.UUID(public_id)
    except ValueError:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Agendamento não encontrado.")
    row = (
        await db.execute(
            select(Appointment, AppointmentItem, Service.name, Barber.name)
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .join(Service, Service.id == AppointmentItem.service_id)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .where(Appointment.public_id == appt_uuid)
            .where(Appointment.created_by_client_session_id == session.id)
        )
    ).first()
    if row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Agendamento não encontrado.")
    appt, item, service_name, barber_name = row
    return appt, item, service_name, barber_name


# ─── POST /me/appointments/{public_id}/cancel ────────────────────────────────

@router.post("/me/appointments/{public_id}/cancel", response_model=PublicAppointmentOut)
@limiter.limit("10/minute")
async def cancel_appointment(
    public_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> PublicAppointmentOut:
    appt, item, service_name, barber_name = await _load_own_appointment(db, session, public_id)

    if appt.status != AppointmentStatus.agendado:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "Este agendamento não pode mais ser cancelado.")
    if appt.start_at <= datetime.now(timezone.utc) + timedelta(hours=settings.public_cancel_min_hours):
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Cancelamento pelo site só até {settings.public_cancel_min_hours}h antes do horário. "
            "Entre em contato com o estabelecimento.",
        )

    appt.status = AppointmentStatus.cancelado
    appt_id = appt.id
    out = _appointment_out(
        appt, item, service_name, barber_name, now=datetime.now(timezone.utc)
    )
    await db.commit()

    background_tasks.add_task(push_appointment, appt_id, org_id, "delete")
    record_event(
        organization_id=org_id,
        action="public.appointment_canceled",
        actor_kind="client",
        resource_type="appointment",
        resource_id=appt_id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return out


# ─── POST /me/appointments/{public_id}/rating ────────────────────────────────


class RatingIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=1000)


class RatingOut(BaseModel):
    rating: int
    comment: Optional[str]
    created_at: str


@router.post(
    "/me/appointments/{public_id}/rating",
    response_model=RatingOut,
    status_code=http_status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
async def rate_appointment(
    body: RatingIn,
    public_id: str,
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> RatingOut:
    """Avaliação pós-atendimento — **definitiva** (sem edição/remoção).

    A tabela nasce append-only (GRANT só SELECT/INSERT, migration 0058); o 409
    de duplicidade é o UNIQUE em `appointment_id`, não uma checagem otimista.
    """
    appt, item, _service_name, _barber_name = await _load_own_appointment(db, session, public_id)

    if appt.status != AppointmentStatus.concluido:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Só é possível avaliar um atendimento concluído.",
        )
    window = timedelta(days=settings.public_rating_window_days)
    if appt.end_at < datetime.now(timezone.utc) - window:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"O prazo para avaliar este atendimento ({settings.public_rating_window_days} dias) já passou.",
        )

    existing = (
        await db.execute(
            select(AppointmentRating.id).where(AppointmentRating.appointment_id == appt.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Este atendimento já foi avaliado.")

    comment = (body.comment or "").strip() or None
    row = AppointmentRating(
        organization_id=org_id,
        appointment_id=appt.id,
        client_id=appt.client_id,
        barber_id=item.barber_id,
        rating=body.rating,
        comment=comment,
    )
    db.add(row)
    await db.flush()
    created_at = row.created_at or datetime.now(timezone.utc)
    appt_id = appt.id
    await db.commit()

    record_event(
        organization_id=org_id,
        action="public.appointment_rated",
        actor_kind="client",
        resource_type="appointment",
        resource_id=appt_id,
        after={"rating": body.rating, "has_comment": comment is not None},
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return RatingOut(
        rating=body.rating,
        comment=comment,
        created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
    )


# ─── POST /me/appointments/{public_id}/reschedule ────────────────────────────


class RescheduleIn(BaseModel):
    service_id: int
    barber_id: int
    start_at: datetime


@router.post("/me/appointments/{public_id}/reschedule", response_model=PublicAppointmentOut)
@limiter.limit("10/minute")
async def reschedule_appointment(
    body: RescheduleIn,
    public_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> PublicAppointmentOut:
    """Remarcação **atômica**: cancela o antigo e cria o novo na MESMA transação.

    Fazer isso em duas chamadas (cancelar + agendar) deixaria o cliente sem
    horário nenhum se a segunda falhasse — daí um endpoint só. O novo passa
    pela mesma validação de grade/conflito e pelo mesmo lock de numeração de
    `book_appointment` (via `_place_appointment`); se ela levantar, nada é
    comitado e o antigo continua `agendado`.
    """
    old_appt, _old_item, _svc_name, _barber_name = await _load_own_appointment(
        db, session, public_id
    )

    if old_appt.status != AppointmentStatus.agendado:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Este agendamento não pode mais ser remarcado.",
        )
    if old_appt.start_at <= datetime.now(timezone.utc) + timedelta(
        hours=settings.public_cancel_min_hours
    ):
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Remarcação pelo site só até {settings.public_cancel_min_hours}h antes do horário. "
            "Entre em contato com o estabelecimento.",
        )

    svc, barber = await _validate_service_barber(db, org_id, body.service_id, body.barber_id)

    # Libera a grade do horário antigo ANTES de validar o novo: sem isso,
    # remarcar para um slot que encosta no próprio agendamento colidiria
    # consigo mesmo. Se `_place_appointment` levantar, o rollback devolve.
    old_id = old_appt.id
    before = {
        "start_at": old_appt.start_at.isoformat(),
        "service_id": _old_item.service_id,
        "barber_id": _old_item.barber_id,
    }
    old_appt.status = AppointmentStatus.cancelado
    await db.flush()

    appt, item = await _place_appointment(
        db, org_id=org_id, session=session, svc=svc, barber=barber, start_at=body.start_at
    )
    new_id = appt.id
    out = _appointment_out(
        appt, item, svc.name, barber.name, now=datetime.now(timezone.utc)
    )
    await db.commit()

    background_tasks.add_task(push_appointment, old_id, org_id, "delete")
    background_tasks.add_task(push_appointment, new_id, org_id, "upsert")
    background_tasks.add_task(push_svc.notify_booking_confirmation, new_id, org_id)
    record_event(
        organization_id=org_id,
        action="public.appointment_rescheduled",
        actor_kind="client",
        resource_type="appointment",
        resource_id=new_id,
        before=before,
        after={
            "start_at": out.start_at,
            "service_id": svc.id,
            "barber_id": barber.id,
            "canceled_appointment_id": old_id,
        },
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return out


# ─── GET/PATCH /me/profile + foto ────────────────────────────────────────────


class ProfileOut(BaseModel):
    name: str
    # Telefone é somente leitura na v1 (sem OTP, D-79) e sai MASCARADO: o
    # cliente só precisa reconhecer o número, não relê-lo por inteiro.
    phone_masked: str
    email: Optional[str]
    photo_url: Optional[str]
    member_since: str


class ProfileUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    email: Optional[EmailStr] = None


async def _load_own_client(db: AsyncSession, session: ClientSession) -> Client:
    client = (
        await db.execute(select(Client).where(Client.id == session.client_id))
    ).scalar_one_or_none()
    if client is None or client.deleted_at is not None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cadastro não encontrado.")
    return client


def _profile_out(client: Client) -> ProfileOut:
    return ProfileOut(
        name=client.name,
        phone_masked=mask_phone(client.phone_e164),
        email=client.email,
        photo_url=media.public_url(client.photo_path),
        member_since=client.created_at.isoformat(),
    )


@router.get("/me/profile", response_model=ProfileOut)
@limiter.limit("60/minute")
async def get_profile(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> ProfileOut:
    return _profile_out(await _load_own_client(db, session))


@router.patch("/me/profile", response_model=ProfileOut)
@limiter.limit("20/minute")
async def update_profile(
    body: ProfileUpdateIn,
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> ProfileOut:
    """Nome e e-mail. **Telefone não entra aqui** — é a chave de identidade do
    cadastro e trocá-lo sem OTP permitiria assumir o cadastro de outra pessoa.
    """
    client = await _load_own_client(db, session)
    before = {"name": client.name, "email": client.email}

    fields = body.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] is not None:
        client.name = fields["name"].strip()
    if "email" in fields:
        client.email = str(fields["email"]) if fields["email"] else None

    await db.flush()
    out = _profile_out(client)
    client_id = client.id
    after = {"name": client.name, "email": client.email}
    await db.commit()

    record_event(
        organization_id=org_id,
        action="public.profile_updated",
        actor_kind="client",
        resource_type="client",
        resource_id=client_id,
        before=before,
        after=after,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return out


@router.put("/me/profile/foto", response_model=ProfileOut)
@limiter.limit("10/minute")
async def upload_profile_photo(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
    file: Annotated[UploadFile, File(description="JPG, PNG, WebP ou HEIC (máx. 8 MB)")],
) -> ProfileOut:
    """Substitui a foto do cliente (molde `equipe.py::enviar_foto_barbeiro`).

    O nome do arquivo vem do `public_id` (UUID) do cliente, não do id numérico:
    `/media` é público sem autenticação e um id sequencial tornaria o acervo de
    fotos de rosto enumerável (ver `app/services/media.py`).
    """
    client = await _load_own_client(db, session)
    raw = await file.read()
    try:
        client.photo_path = media.save_client_photo(
            org_id, client.public_id, raw, file.content_type
        )
    except media.MediaError as exc:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc

    await db.flush()
    out = _profile_out(client)
    client_id = client.id
    await db.commit()

    record_event(
        organization_id=org_id,
        action="public.profile_photo_updated",
        actor_kind="client",
        resource_type="client",
        resource_id=client_id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return out


@router.delete("/me/profile/foto", response_model=ProfileOut)
@limiter.limit("10/minute")
async def delete_profile_photo(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> ProfileOut:
    """Volta para a inicial do nome. Idempotente."""
    client = await _load_own_client(db, session)
    client.photo_path = None
    await db.flush()
    out = _profile_out(client)
    client_id = client.id
    public_uuid = client.public_id
    await db.commit()

    # Só apaga o arquivo depois de o campo sair do banco (molde D-85): se o
    # disco falhar, sobra órfão invisível — nunca linha apontando para o vazio.
    media.delete_client_photo(org_id, public_uuid)
    record_event(
        organization_id=org_id,
        action="public.profile_photo_deleted",
        actor_kind="client",
        resource_type="client",
        resource_id=client_id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return out


# ─── POST /auth/logout ───────────────────────────────────────────────────────

@router.post("/auth/logout", status_code=http_status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> None:
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    response.delete_cookie(
        SESSION_COOKIE, domain=settings.public_cookie_domain or None, path="/"
    )


# ─── POST/DELETE /push/subscription ──────────────────────────────────────────


class PublicSubscribeIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    user_agent: Optional[str] = None


@router.post("/push/subscription", status_code=http_status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def public_subscribe_push(
    body: PublicSubscribeIn,
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> None:
    await db.execute(
        pg_insert(PushSubscription)
        .values(
            organization_id=org_id,
            subscriber_type=PushSubscriberType.client,
            user_id=None,
            client_id=session.client_id,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth_key=body.auth,
            user_agent=body.user_agent,
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={
                "client_id": session.client_id,
                "user_id": None,
                "subscriber_type": PushSubscriberType.client,
                "p256dh": body.p256dh,
                "auth_key": body.auth,
                "user_agent": body.user_agent,
                "revoked_at": None,
            },
        )
    )
    await db.commit()


class PublicUnsubscribeIn(BaseModel):
    endpoint: str


@router.delete("/push/subscription", status_code=http_status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def public_unsubscribe_push(
    body: PublicUnsubscribeIn,
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> None:
    row = (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == body.endpoint,
                PushSubscription.client_id == session.client_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Subscrição não encontrada.")
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()


# ─── POST/DELETE /push/device (app nativo, FCM) ──────────────────────────────


class PublicDeviceIn(BaseModel):
    token: str = Field(min_length=8, max_length=4096)
    platform: str = Field(pattern="^(ios|android)$")


def _fcm_endpoint(token: str) -> str:
    """Device token do FCM no mesmo campo `endpoint` do Web Push.

    Prefixo `fcm:` mantém upsert por `endpoint` e revogação valendo nos dois
    canais sem tabela nova (ver migration 0060).
    """
    return f"fcm:{token}"


@router.post("/push/device", status_code=http_status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def public_register_device(
    body: PublicDeviceIn,
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> None:
    await db.execute(
        pg_insert(PushSubscription)
        .values(
            organization_id=org_id,
            subscriber_type=PushSubscriberType.client,
            user_id=None,
            client_id=session.client_id,
            endpoint=_fcm_endpoint(body.token),
            channel=PushChannel.fcm,
            # Chaves do Web Push não existem no FCM (CHECK do canal na 0060).
            p256dh=None,
            auth_key=None,
            device_platform=body.platform,
            user_agent=(request.headers.get("user-agent") or "")[:500] or None,
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={
                "client_id": session.client_id,
                "user_id": None,
                "subscriber_type": PushSubscriberType.client,
                "channel": PushChannel.fcm,
                "p256dh": None,
                "auth_key": None,
                "device_platform": body.platform,
                "revoked_at": None,
            },
        )
    )
    await db.commit()


class PublicDeviceDeleteIn(BaseModel):
    token: str


@router.delete("/push/device", status_code=http_status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def public_unregister_device(
    body: PublicDeviceDeleteIn,
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> None:
    row = (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == _fcm_endpoint(body.token),
                PushSubscription.client_id == session.client_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Dispositivo não encontrado.")
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()


# ─── assinatura online (Stripe Connect, Feature 2) ───────────────────────────
#
# Regra de ouro deste bloco: o checkout NÃO cria assinatura. Ele grava um
# `MembershipOrder` pendente e devolve a URL da Stripe. Quem cria o
# `ClientMembership` é o webhook (`app/api/connect.py`), depois de a Stripe
# confirmar o pagamento — assim ninguém ganha pacote abandonando o checkout.


class PublicPlanOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    included_uses: Optional[int] = None
    duration_days: int
    services: list[str]
    # ── vitrine / order bump (0065) ──────────────────────────────────────
    audience: str = "unissex"
    category: Optional[str] = None
    headline: Optional[str] = None
    perks: list[str] = []
    badge: Optional[str] = None
    is_featured: bool = False
    # Soma do preço avulso dos serviços do combo (base do "você economiza").
    avulso_equivalente: float = 0.0


class PublicPlansOut(BaseModel):
    plans: list[PublicPlanOut]


class CheckoutIn(BaseModel):
    plan_id: int


class CheckoutOut(BaseModel):
    checkout_url: str
    order_public_id: str


class MyMembershipOut(BaseModel):
    public_id: str
    plan_name: Optional[str]
    status: str
    start_at: str
    end_at: str
    included_uses: Optional[int]
    used_uses: int
    services: list[str]


def _sells_online(org: Organization) -> bool:
    """A org só vende assinatura no site com a feature ligada E a conta apta.

    Fail closed nos três eixos: kill switch da instalação, conta conectada
    existente e `charges_enabled` confirmado pela Stripe.
    """
    return bool(
        settings.connect_enabled
        and org.stripe_connected_account_id
        and org.stripe_connect_charges_enabled
    )


async def _load_org(db: AsyncSession, org_id: int) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Estabelecimento não encontrado.")
    return org


async def _plan_services(db: AsyncSession, plan_ids: list[int]) -> dict[int, list[str]]:
    if not plan_ids:
        return {}
    rows = (
        await db.execute(
            select(MembershipPlanItem.plan_id, Service.name)
            .join(Service, Service.id == MembershipPlanItem.service_id)
            .where(MembershipPlanItem.plan_id.in_(plan_ids))
            .order_by(MembershipPlanItem.plan_id, MembershipPlanItem.position)
        )
    ).all()
    out: dict[int, list[str]] = {}
    for plan_id, service_name in rows:
        out.setdefault(plan_id, []).append(service_name)
    return out


async def _plan_avulso_totals(db: AsyncSession, plan_ids: list[int]) -> dict[int, float]:
    """Preço avulso somado do combo de cada plano (base do 'você economiza')."""
    if not plan_ids:
        return {}
    rows = (
        await db.execute(
            select(
                MembershipPlanItem.plan_id,
                func.coalesce(func.sum(Service.price), 0),
            )
            .join(Service, Service.id == MembershipPlanItem.service_id)
            .where(MembershipPlanItem.plan_id.in_(plan_ids))
            .group_by(MembershipPlanItem.plan_id)
        )
    ).all()
    return {plan_id: float(total) for plan_id, total in rows}


@router.get("/planos", response_model=PublicPlansOut)
@limiter.limit("60/minute")
async def public_plans(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
) -> PublicPlansOut:
    """Planos vendáveis online. Lista VAZIA enquanto a org não puder cobrar.

    O resultado é cacheado sempre — inclusive o vazio. O que garante coerência
    é a invalidação da tag `public-plans` em `POST /connect/sync` e no webhook
    `account.updated` (`app/api/connect.py`), que são os únicos pontos em que a
    capacidade de cobrar muda.
    """
    cache_key = plans_cache_key(org_id)
    try:
        cached = await get_redis().get(cache_key)
        if cached:
            return PublicPlansOut(**json.loads(cached))
    except Exception:
        pass  # cache é otimização; Redis fora não derruba a vitrine

    org = await _load_org(db, org_id)
    plans: list[PublicPlanOut] = []
    if _sells_online(org):
        rows = (
            (
                await db.execute(
                    select(MembershipPlan)
                    .where(MembershipPlan.is_active.is_(True))
                    .where(MembershipPlan.deleted_at.is_(None))
                    .order_by(
                        MembershipPlan.display_order,
                        MembershipPlan.price,
                        MembershipPlan.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        services_by_plan = await _plan_services(db, [p.id for p in rows])
        avulso_by_plan = await _plan_avulso_totals(db, [p.id for p in rows])
        plans = [
            PublicPlanOut(
                id=p.id,
                name=p.name,
                description=p.description,
                price=float(p.price),
                included_uses=p.included_uses,
                duration_days=p.duration_days,
                services=services_by_plan.get(p.id, []),
                audience=(
                    p.audience.value if hasattr(p.audience, "value") else p.audience
                ),
                category=p.category,
                headline=p.headline,
                perks=list(p.perks or []),
                badge=p.badge,
                is_featured=p.is_featured,
                avulso_equivalente=avulso_by_plan.get(p.id, 0.0),
            )
            for p in rows
            # plano sem combo não é vendável (a criação da assinatura recusaria)
            if services_by_plan.get(p.id)
        ]

    out = PublicPlansOut(plans=plans)
    try:
        await get_redis().setex(
            cache_key, PLANS_CACHE_TTL_SECONDS, out.model_dump_json()
        )
    except Exception:
        pass
    return out


@router.post(
    "/memberships/checkout",
    response_model=CheckoutOut,
    status_code=http_status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def create_membership_checkout(
    body: CheckoutIn,
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> CheckoutOut:
    org = await _load_org(db, org_id)
    if not _sells_online(org):
        raise HTTPException(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "Pagamento online indisponível neste estabelecimento.",
        )

    plan = (
        await db.execute(
            select(MembershipPlan).where(MembershipPlan.id == body.plan_id)
        )
    ).scalar_one_or_none()
    if plan is None or plan.deleted_at is not None or not plan.is_active:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Plano não encontrado.")
    servicos = (await _plan_services(db, [plan.id])).get(plan.id, [])
    if not servicos:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Plano sem combo configurado.",
        )

    # Renovação pelo site fica fora da v1: com uma assinatura vigente, a compra
    # de outra teria que decidir empilhar ou substituir — decisão de negócio.
    if await membership_svc.active_memberships_for_client(db, session.client_id):
        raise HTTPException(
            http_status.HTTP_409_CONFLICT, "Você já tem uma assinatura ativa."
        )

    amount_cents = int((plan.price * 100).to_integral_value())
    fee_cents = connect_svc.resolve_fee_cents(org, amount_cents)

    client = (
        await db.execute(select(Client).where(Client.id == session.client_id))
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    order = MembershipOrder(
        organization_id=org_id,
        client_id=session.client_id,
        client_session_id=session.id,
        plan_id=plan.id,
        plan_name=plan.name,
        price=plan.price,
        included_uses=plan.included_uses,
        duration_days=plan.duration_days,
        combo_snapshot=servicos,
        status="pending",
        provider="stripe_connect",
        connected_account_id=org.stripe_connected_account_id,
        amount_cents=amount_cents,
        application_fee_cents=fee_cents,
        currency="brl",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db.add(order)
    await db.flush()

    # URLs montadas NO SERVIDOR (nunca aceitas do corpo — open-redirect).
    base = (settings.public_site_url or "").rstrip("/")
    success_url = f"{base}/assinatura/sucesso?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/assinatura?cancelado=1"

    provider = get_connect_provider()
    try:
        stripe_session = await provider.create_checkout_session(
            account_id=org.stripe_connected_account_id,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            currency="brl",
            product_name=plan.name,
            client_reference_id=str(order.public_id),
            customer_email=client.email,
            metadata={
                "organization_id": str(org_id),
                "membership_order_id": str(order.id),
                "plan_id": str(plan.id),
            },
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except ConnectProviderError as exc:
        # Sem sessão na Stripe não há como pagar: o pedido não pode ficar
        # pendurado esperando um webhook que nunca virá.
        await db.rollback()
        raise HTTPException(
            http_status.HTTP_502_BAD_GATEWAY, "Não foi possível iniciar o pagamento."
        ) from exc

    order.provider_session_id = stripe_session["session_id"]
    order_public_id = str(order.public_id)
    order_id = order.id
    await db.commit()

    record_event(
        organization_id=org_id,
        actor_kind="client",
        action="memberships.checkout_started",
        resource_type="membership_order",
        resource_id=order_id,
        after={"plan_id": plan.id, "amount_cents": amount_cents},
        ip=_client_ip(request),
    )
    return CheckoutOut(
        checkout_url=stripe_session["checkout_url"], order_public_id=order_public_id
    )


@router.get("/me/assinatura", response_model=Optional[MyMembershipOut])
@limiter.limit("60/minute")
async def my_membership(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
    session: Annotated[ClientSession, Depends(get_client_session)],
) -> Optional[MyMembershipOut]:
    """Assinatura vigente da sessão atual (ou `null`).

    É o que a página de sucesso consulta em polling curto: a confirmação vem
    SEMPRE do webhook, nunca da `success_url` (que o cliente controla).
    """
    membership = await membership_svc.active_membership_for_client(
        db, session.client_id
    )
    if membership is None:
        return None
    # Nome do plano por consulta explícita: `membership.plan` é lazy e um
    # acesso implícito aqui estouraria MissingGreenlet no contexto async.
    plan_name = None
    if membership.plan_id is not None:
        plan_name = (
            await db.execute(
                select(MembershipPlan.name).where(MembershipPlan.id == membership.plan_id)
            )
        ).scalar_one_or_none()
    return MyMembershipOut(
        public_id=str(membership.public_id),
        plan_name=plan_name,
        status=membership.status.value,
        start_at=membership.start_at.isoformat(),
        end_at=membership.end_at.isoformat(),
        included_uses=membership.included_uses,
        used_uses=membership.used_uses,
        services=[
            item.get("name", "") if isinstance(item, dict) else str(item)
            for item in (membership.combo_snapshot or [])
        ],
    )
