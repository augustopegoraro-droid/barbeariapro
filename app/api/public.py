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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.phone import normalize_phone
from app.core.rate_limit import limiter
from app.core.security import generate_refresh_token, hash_refresh_token
from app.db.redis import get_redis
from app.db.session import get_db, set_current_org
from app.services.audit import record_event
from app.services.availability import free_slots
from app.services.calendar_sync import push_appointment
from app.services.scheduling import barber_has_conflict
from app.services.tenant import org_id_by_subdomain
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BarberService,
    BusinessHours,
    Client,
    ClientSession,
    ClientVisibilitySettings,
    ContactChannel,
    Organization,
    Service,
    Unit,
)

router = APIRouter(prefix="/public/{subdomain}", tags=["public"])
logger = logging.getLogger(__name__)

SESSION_COOKIE = "tt_session"
INFO_CACHE_TTL_SECONDS = 60


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


class SessionCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=25)


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
    start_at: str
    end_at: str
    status: str
    total_amount: float
    cancelable: bool


# ─── GET /info ───────────────────────────────────────────────────────────────

@router.get("/info", response_model=PublicInfoOut)
@limiter.limit("60/minute")
async def public_info(
    request: Request,
    subdomain: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Annotated[int, Depends(get_public_org)],
) -> PublicInfoOut:
    cache_key = f"public_info:{org_id}"
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
            PublicProfessionalOut(id=b.id, name=b.name, specialty=b.specialty)
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

    if body.start_at.tzinfo is None:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "start_at deve incluir fuso horário.")
    start_utc = body.start_at.astimezone(timezone.utc)
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
    appt_id = appt.id
    public_id = str(appt.public_id)
    start_iso = appt.start_at.isoformat()
    end_iso = appt.end_at.isoformat()

    db.add(
        AppointmentItem(
            organization_id=org_id,
            appointment_id=appt_id,
            service_id=svc.id,
            barber_id=barber.id,
            price_charged=price,
            duration_minutes=svc.default_duration_min,
        )
    )
    await db.commit()

    background_tasks.add_task(push_appointment, appt_id, org_id, "upsert")
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
    return PublicAppointmentOut(
        public_id=public_id,
        service_name=svc.name,
        barber_name=barber.name,
        start_at=start_iso,
        end_at=end_iso,
        status="agendado",
        total_amount=price,
        cancelable=True,
    )


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
    min_cancel = timedelta(hours=settings.public_cancel_min_hours)
    return [
        PublicAppointmentOut(
            public_id=str(appt.public_id),
            service_name=service_name,
            barber_name=barber_name,
            start_at=appt.start_at.isoformat(),
            end_at=appt.end_at.isoformat(),
            status=appt.status.value,
            total_amount=float(appt.total_amount),
            cancelable=(
                appt.status == AppointmentStatus.agendado
                and appt.start_at > now + min_cancel
            ),
        )
        for appt, _item, service_name, barber_name in rows
    ]


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
    appt, _item, service_name, barber_name = row

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
    out = PublicAppointmentOut(
        public_id=str(appt.public_id),
        service_name=service_name,
        barber_name=barber_name,
        start_at=appt.start_at.isoformat(),
        end_at=appt.end_at.isoformat(),
        status="cancelado",
        total_amount=float(appt.total_amount),
        cancelable=False,
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
