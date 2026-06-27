# file: app/api/bot.py
"""Endpoints consumidos pelo chatbot n8n (auth via X-Bot-Token)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import local_tz
from app.core.phone import normalize_phone
from app.deps import get_bot_db
from app.services.scheduling import barber_has_conflict
from app.services.lead_funnel import advance_lead_on_inbound
from app.services.loyalty import recalculate as _recalculate_loyalty
import app.services.conversation as _conv_svc
from app.services.conversation import MediaIn as _MediaIn
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    BarberService,
    BarberUnit,
    BusinessHours,
    Client,
    ClientConsent,
    ConsentStatus,
    ContactChannel,
    Lead,
    LeadEvent,
    MessageLog,
    Service,
    TimeOff,
    Unit,
)
from models.enums import (DeliveryStatus, LeadStage, MessageDirection,
                          MessageSenderType, MessageType, AttachmentMediaType)

router = APIRouter(prefix="/bot", tags=["bot"])
BotDB = Annotated[AsyncSession, Depends(get_bot_db)]

_SLOT_STEP = 30  # minutos entre slots

# ---------------------------------------------------------------------------
# Debounce buffer — concorrência via asyncio.Lock por telefone
# ---------------------------------------------------------------------------
import asyncio as _asyncio
import logging as _logging
from time import monotonic as _mono

_debounce_lock = _asyncio.Lock()
_debounce: dict[str, dict] = {}       # phone → {messages: list[str], ts: float}
_last_flush: dict[str, float] = {}    # phone → monotonic ts do último flush
_DEBOUNCE_STALE = 30.0                # buffer morto após 30s sem flush
_SESSION_GAP = 4 * 3600.0            # gap > 4h desde o último flush → nova sessão

# Camada 1 — deduplicação por message_id (redelivery exato)
_seen_ids: dict[str, float] = {}
_SEEN_TTL = 24 * 3600.0              # descarta entradas com mais de 24h

# Camada 2 — deduplicação por conteúdo (redelivery tardio: mesmo texto no mesmo phone ≤ 30s)
_seen_content: dict[str, float] = {}  # "phone:msg_normalizado" → monotonic ts
_CONTENT_TTL = 30.0

_logger = _logging.getLogger(__name__)


def _normalize_msg(text: str) -> str:
    """Normalização mínima para comparar conteúdo: lowercase + colapso de espaços."""
    return " ".join(text.lower().split())


def _purge_seen_ids(now: float) -> None:
    """Remove message_ids expirados (chamado dentro do lock)."""
    expired = [k for k, ts in _seen_ids.items() if now - ts > _SEEN_TTL]
    for k in expired:
        del _seen_ids[k]


def _purge_seen_content(now: float) -> None:
    """Remove entradas de conteúdo expiradas (chamado dentro do lock)."""
    expired = [k for k, ts in _seen_content.items() if now - ts > _CONTENT_TTL]
    for k in expired:
        del _seen_content[k]


class _DebounceIn(BaseModel):
    phone: str
    message: str
    message_id: Optional[str] = None  # ID da mensagem do WhatsApp para deduplicação


class _DebounceOut(BaseModel):
    proceed: bool
    is_new_session: bool = False


class _FlushIn(BaseModel):
    phone: str


class _FlushOut(BaseModel):
    message: str
    is_new_session: bool = False


def _require_bot_token(
    x_bot_token: Annotated[Optional[str], Header(alias="X-Bot-Token")] = None,
) -> None:
    from app.core.config import settings
    if not settings.bot_api_key or x_bot_token != settings.bot_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Bot token inválido")


_BotAuth = Annotated[None, Depends(_require_bot_token)]


@router.post("/debounce", response_model=_DebounceOut)
async def debounce_entry(body: _DebounceIn, _auth: _BotAuth = None):
    """Registra mensagem no buffer. Retorna proceed=True apenas para o primeiro
    da rajada; os demais retornam proceed=False e encerram no n8n.
    Camada 1: ignora re-deliveries exatos via message_id.
    Camada 2: ignora re-deliveries tardios via conteúdo normalizado (30s).
    Detecta nova sessão por gap de tempo."""
    phone = body.phone
    async with _debounce_lock:
        now = _mono()

        # Camada 1 — deduplicação por message_id (redelivery exato)
        if body.message_id:
            _purge_seen_ids(now)
            if body.message_id in _seen_ids:
                return _DebounceOut(proceed=False, is_new_session=False)
            _seen_ids[body.message_id] = now

        # Camada 2 — deduplicação por conteúdo normalizado (redelivery tardio ≤ 30s)
        if body.message:
            content_key = f"{phone}:{_normalize_msg(body.message)}"
            _purge_seen_content(now)
            if content_key in _seen_content:
                elapsed = now - _seen_content[content_key]
                _logger.warning(
                    "redelivery_suspected phone=%s elapsed_s=%.1f message_id=%s",
                    phone, elapsed, body.message_id or "none",
                )
                return _DebounceOut(proceed=False, is_new_session=False)
            _seen_content[content_key] = now

        buf = _debounce.get(phone)

        # Detectar nova sessão: compara o momento do último flush com agora
        # Se não há registro de flush anterior, é definitivamente uma nova sessão
        last_flush_ts = _last_flush.get(phone)
        if last_flush_ts is None:
            is_new_session = True
        else:
            is_new_session = (now - last_flush_ts) > _SESSION_GAP

        if buf is None or (now - buf["ts"]) > _DEBOUNCE_STALE:
            _debounce[phone] = {
                "messages": [body.message],
                "ts": now,
                "is_new_session": is_new_session,
            }
            return _DebounceOut(proceed=True, is_new_session=is_new_session)

        buf["messages"].append(body.message)
        buf["ts"] = now
        return _DebounceOut(proceed=False, is_new_session=False)


@router.post("/debounce/flush", response_model=_FlushOut)
async def debounce_flush(body: _FlushIn, _auth: _BotAuth = None):
    """Lê e limpa o buffer. Chamado pelo controller após o Wait de 5s."""
    async with _debounce_lock:
        buf = _debounce.pop(body.phone, None)
        if buf is not None:
            _last_flush[body.phone] = _mono()
    messages = buf["messages"] if buf else []
    is_new_session = buf.get("is_new_session", False) if buf else False
    return _FlushOut(message="\n".join(messages), is_new_session=is_new_session)


class _DebugSessionIn(BaseModel):
    phone: str
    minutes_ago: int = Field(..., description="Simula último flush X minutos atrás (para testes)")


@router.post("/debounce/debug-set-session", include_in_schema=False)
async def debug_set_session(_auth: _BotAuth, body: _DebugSessionIn):
    """DEBUG ONLY — simula sessão antiga para testar detecção de nova sessão.

    Desabilitado por padrão; habilitar via ENABLE_DEBUG_ENDPOINTS=true (somente dev).
    """
    if not settings.enable_debug_endpoints:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    async with _debounce_lock:
        _debounce.pop(body.phone, None)
        _last_flush[body.phone] = _mono() - (body.minutes_ago * 60.0)
    return {"ok": True, "simulated_minutes_ago": body.minutes_ago}


# ---------------------------------------------------------------------------
# Schemas de saída/entrada
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Log de mensagens (conversa WhatsApp)
# ---------------------------------------------------------------------------


class _MediaPayload(BaseModel):
    media_type: str
    url: Optional[str] = None
    mime: Optional[str] = None
    size_bytes: Optional[int] = None
    duration_s: Optional[int] = None
    transcript: Optional[str] = None
    caption: Optional[str] = None

    def to_domain(self) -> _MediaIn:
        return _MediaIn(
            media_type=AttachmentMediaType(self.media_type),
            url=self.url,
            mime=self.mime,
            size_bytes=self.size_bytes,
            duration_s=self.duration_s,
            transcript=self.transcript,
            caption=self.caption,
        )


class _MessageLogIn(BaseModel):
    phone: str
    direction: str
    body: Optional[str] = None
    whatsapp_message_id: Optional[str] = None
    message_type: str = "text"
    media: Optional[_MediaPayload] = None


@router.post("/messages", status_code=200)
async def log_message(body: _MessageLogIn, db: BotDB, _auth: _BotAuth = None):
    """Grava mensagem recebida ou enviada no histórico de conversa.

    Chamado pelo n8n após debounce/flush (inbound) e após resposta do AI Agent
    (outbound). Idempotente via whatsapp_message_id (namespaced por conversa+direção).
    Grava mesmo sem cliente cadastrado (1º contato).
    """
    phone = _normalize_phone(body.phone)
    org_id = settings.bot_organization_id
    direction = MessageDirection(body.direction)
    now = datetime.now(timezone.utc)

    _logger.info(
        "conversation_log direction=%s phone=%s wamid=%s body_len=%d",
        direction.value, phone, body.whatsapp_message_id or "none",
        len(body.body or ""),
    )

    client = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()

    sender = (MessageSenderType.client if direction == MessageDirection.inbound
              else MessageSenderType.bot)

    msg = await _conv_svc.record_message(
        db,
        org_id=org_id,
        phone=phone,
        sender_type=sender,
        body=body.body,
        message_type=MessageType(body.message_type),
        wa_message_id=body.whatsapp_message_id,
        client_id=client.id if client else None,
        media=body.media.to_domain() if body.media else None,
    )

    if msg is None:
        await db.commit()
        return {"ok": True, "duplicate": True}

    # ── avanço de estágio do funil — caminho ÚNICO (helper compartilhado com /chatwoot) ──
    if direction == MessageDirection.inbound and client is not None:
        await advance_lead_on_inbound(db, org_id=org_id, client_id=client.id, now=now)

    await db.commit()
    _logger.info("conversation_log saved direction=%s phone=%s", direction.value, phone)
    return {"ok": True, "duplicate": False}


# ---------------------------------------------------------------------------
# Schemas de saída/entrada
# ---------------------------------------------------------------------------


class ServiceOut(BaseModel):
    id: int
    name: str
    category: str
    price: Decimal
    duration_min: int


class BarberOut(BaseModel):
    id: int
    name: str
    specialty: Optional[str] = None


class ClientUpsertIn(BaseModel):
    phone: str = Field(..., description="Telefone E.164 ex: +5511999998888")
    name: str


class ClientOut(BaseModel):
    id: int
    name: str
    phone_e164: str


class ClientProfileOut(BaseModel):
    found: bool
    id: Optional[int] = None
    name: Optional[str] = None
    total_appointments: int = 0
    last_visit_date: Optional[str] = None
    days_since_last_visit: Optional[int] = None
    last_barber_name: Optional[str] = None
    last_service_name: Optional[str] = None
    preferred_time: Optional[str] = None
    has_photo_reference: bool = False
    last_photo_description: Optional[str] = None
    favorite_barber_id: Optional[int] = None
    favorite_barber_name: Optional[str] = None
    favorite_service_name: Optional[str] = None


class Slot(BaseModel):
    start: str       # "09:00"
    end: str         # "09:30"
    start_iso: str   # ISO com fuso


class AvailabilityOut(BaseModel):
    date: str
    barber_id: int
    barber_name: str
    service_duration_min: int
    slots: List[Slot]


class AppointmentCreateIn(BaseModel):
    client_id: int
    barber_id: int
    service_id: int
    start_at: datetime = Field(
        ..., description="ISO 8601 com fuso ex: 2026-06-05T09:00:00-03:00"
    )


class AppointmentOut(BaseModel):
    id: int
    public_id: str
    barber_name: str
    service_name: str
    start_at: str
    end_at: str
    status: str
    total_amount: Decimal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Telefone inválido: '{raw}'. Use formato E.164 (+5511999998888)",
        )


def _overlaps(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> bool:
    return s2 < e1 and e2 > s1


def _appt_out(appt: Appointment, barber_name: str, svc_name: str) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        public_id=str(appt.public_id),
        barber_name=barber_name,
        service_name=svc_name,
        start_at=appt.start_at.isoformat(),
        end_at=appt.end_at.isoformat(),
        status=appt.status.value,
        total_amount=appt.total_amount,
    )


# ---------------------------------------------------------------------------
# Serviços
# ---------------------------------------------------------------------------


@router.get("/services", response_model=List[ServiceOut])
async def list_services(db: BotDB) -> list:
    rows = (
        await db.execute(select(Service).where(Service.is_active.is_(True)))
    ).scalars().all()
    return [
        ServiceOut(
            id=s.id,
            name=s.name,
            category=s.category.value,
            price=s.price,
            duration_min=s.default_duration_min,
        )
        for s in rows
    ]


# ---------------------------------------------------------------------------
# Barbeiros
# ---------------------------------------------------------------------------


@router.get("/barbers", response_model=List[BarberOut])
async def list_barbers(db: BotDB) -> list:
    rows = (
        await db.execute(
            select(Barber)
            .join(BarberUnit, BarberUnit.barber_id == Barber.id)
            .where(BarberUnit.unit_id == settings.bot_unit_id)
            .where(Barber.deleted_at.is_(None))
        )
    ).scalars().all()
    return [BarberOut(id=b.id, name=b.name, specialty=b.specialty) for b in rows]


# ---------------------------------------------------------------------------
# Clientes (upsert por telefone)
# ---------------------------------------------------------------------------


@router.post("/clients", response_model=ClientOut, status_code=status.HTTP_200_OK)
async def upsert_client(body: ClientUpsertIn, db: BotDB) -> ClientOut:
    phone = _normalize_phone(body.phone)
    org_id = settings.bot_organization_id

    existing = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()

    _active_lead_stages = {LeadStage.novo_contato, LeadStage.conversando}

    if existing:
        # Só atualiza se o novo nome for mais informativo (mais caracteres)
        if len(body.name) > len(existing.name or ""):
            existing.name = body.name
        client = existing

        # Cliente existente: criar lead se não tiver um ativo recente (últimos 7 dias)
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        recent_lead = (
            await db.execute(
                select(Lead)
                .where(Lead.client_id == client.id)
                .where(Lead.organization_id == org_id)
                .where(Lead.stage.in_(_active_lead_stages))
                .where(Lead.created_at >= cutoff)
                .limit(1)
            )
        ).scalar_one_or_none()

        if recent_lead is None:
            max_pos = (
                await db.execute(
                    select(func.max(Lead.position)).where(
                        Lead.organization_id == org_id,
                        Lead.stage == LeadStage.novo_contato,
                    )
                )
            ).scalar_one_or_none()
            lead = Lead(
                organization_id=org_id,
                client_id=client.id,
                name=client.name,
                phone_e164=phone,
                source=ContactChannel.whatsapp,
                stage=LeadStage.novo_contato,
                position=(max_pos + 1) if max_pos is not None else 0,
                last_contact_at=datetime.now(timezone.utc),
            )
            db.add(lead)
            await db.flush()
            db.add(LeadEvent(
                lead_id=lead.id,
                organization_id=org_id,
                event_type="created",
                to_stage=LeadStage.novo_contato,
            ))
        else:
            # Lead ativo já existe: atualizar timestamp de contato.
            recent_lead.last_contact_at = datetime.now(timezone.utc)
            recent_lead.updated_at = datetime.now(timezone.utc)
    else:
        client = Client(
            organization_id=org_id,
            name=body.name,
            phone_e164=phone,
            acquisition_channel=ContactChannel.whatsapp,
        )
        db.add(client)
        await db.flush()
        db.add(
            ClientConsent(
                client_id=client.id,
                channel=ContactChannel.whatsapp,
                status=ConsentStatus.opt_in,
                source="chatbot_first_contact",
            )
        )

        # Novo contato via WhatsApp → criar lead no funil
        max_pos = (
            await db.execute(
                select(func.max(Lead.position)).where(
                    Lead.organization_id == org_id,
                    Lead.stage == LeadStage.novo_contato,
                )
            )
        ).scalar_one_or_none()
        lead = Lead(
            organization_id=org_id,
            client_id=client.id,
            name=client.name,
            phone_e164=phone,
            source=ContactChannel.whatsapp,
            stage=LeadStage.novo_contato,
            position=(max_pos + 1) if max_pos is not None else 0,
        )
        db.add(lead)
        await db.flush()
        db.add(LeadEvent(
            lead_id=lead.id,
            organization_id=org_id,
            event_type="created",
            to_stage=LeadStage.novo_contato,
        ))

    return ClientOut(id=client.id, name=client.name, phone_e164=client.phone_e164)


class ClientPhotoIn(BaseModel):
    phone: str
    photo_url: str
    description: Optional[str] = None


@router.patch("/clients/photo", status_code=200)
async def update_client_photo(body: ClientPhotoIn, db: BotDB, _auth: _BotAuth = None):
    """Salva URL e descrição gerada por Vision da última foto de referência."""
    phone = _normalize_phone(body.phone)
    org_id = settings.bot_organization_id

    client = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()

    if not client:
        return {"ok": False, "reason": "client_not_found"}

    client.last_photo_url = body.photo_url
    if body.description:
        client.last_photo_description = body.description
    return {"ok": True}


@router.get("/clients/profile", response_model=ClientProfileOut)
async def get_client_profile(phone: str, db: BotDB) -> ClientProfileOut:
    phone = _normalize_phone(phone)
    org_id = settings.bot_organization_id

    client = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()

    if not client:
        return ClientProfileOut(found=False)

    total = (
        await db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.client_id == client.id)
            .where(Appointment.status != AppointmentStatus.cancelado)
        )
    ).scalar_one()

    now_utc = datetime.now(timezone.utc)

    # Última visita: preferir status 'concluido' (confirmado), fallback para
    # agendamentos passados não cancelados (aproximação até ter marcação manual)
    last_appt = (
        await db.execute(
            select(Appointment)
            .where(Appointment.client_id == client.id)
            .where(Appointment.status == AppointmentStatus.concluido)
            .order_by(Appointment.start_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if last_appt is None:
        # Fallback: qualquer passado não cancelado
        last_appt = (
            await db.execute(
                select(Appointment)
                .where(Appointment.client_id == client.id)
                .where(Appointment.status != AppointmentStatus.cancelado)
                .where(Appointment.status != AppointmentStatus.faltou)
                .where(Appointment.start_at < now_utc)
                .order_by(Appointment.start_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    days_since = None
    last_date = None
    last_barber_name = None
    last_service_name = None
    if last_appt:
        appt_utc = last_appt.start_at if last_appt.start_at.tzinfo else last_appt.start_at.replace(tzinfo=timezone.utc)
        days_since = (now_utc - appt_utc).days
        last_date = appt_utc.astimezone(local_tz()).date().isoformat()

        last_item_row = (
            await db.execute(
                select(Barber.name, Service.name)
                .select_from(AppointmentItem)
                .join(Barber, Barber.id == AppointmentItem.barber_id)
                .join(Service, Service.id == AppointmentItem.service_id)
                .where(AppointmentItem.appointment_id == last_appt.id)
                .limit(1)
            )
        ).first()
        if last_item_row:
            last_barber_name = last_item_row[0]
            last_service_name = last_item_row[1]

    # Horário preferido: mode do hour dos agendamentos passados convertido para Palmas (UTC-3)
    times_result = (
        await db.execute(
            select(
                func.extract(
                    "hour", func.timezone(settings.app_timezone, Appointment.start_at)
                ).label("hour")
            )
            .where(Appointment.client_id == client.id)
            .where(Appointment.status != AppointmentStatus.cancelado)
            .where(Appointment.start_at < now_utc)
        )
    ).all()
    preferred_time = None
    if times_result:
        hours_local = [int(r.hour) for r in times_result]
        mode_hour = max(set(hours_local), key=hours_local.count)
        preferred_time = f"{mode_hour:02d}:00"

    fav_barber_row = (
        await db.execute(
            select(AppointmentItem.barber_id, func.count().label("cnt"))
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(Appointment.client_id == client.id)
            .where(Appointment.status != AppointmentStatus.cancelado)
            .group_by(AppointmentItem.barber_id)
            .order_by(func.count().desc())
            .limit(1)
        )
    ).first()

    fav_barber_id = fav_barber_name = None
    if fav_barber_row:
        fav_barber_id = fav_barber_row[0]
        b = (await db.execute(select(Barber).where(Barber.id == fav_barber_id))).scalar_one_or_none()
        if b:
            fav_barber_name = b.name

    fav_svc_row = (
        await db.execute(
            select(AppointmentItem.service_id, func.count().label("cnt"))
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(Appointment.client_id == client.id)
            .where(Appointment.status != AppointmentStatus.cancelado)
            .group_by(AppointmentItem.service_id)
            .order_by(func.count().desc())
            .limit(1)
        )
    ).first()

    fav_svc_name = None
    if fav_svc_row:
        s = (await db.execute(select(Service).where(Service.id == fav_svc_row[0]))).scalar_one_or_none()
        if s:
            fav_svc_name = s.name

    return ClientProfileOut(
        found=True,
        id=client.id,
        name=client.name,
        total_appointments=total or 0,
        last_visit_date=last_date,
        days_since_last_visit=days_since,
        last_barber_name=last_barber_name,
        last_service_name=last_service_name,
        preferred_time=preferred_time,
        has_photo_reference=bool(client.last_photo_url),
        last_photo_description=client.last_photo_description,
        favorite_barber_id=fav_barber_id,
        favorite_barber_name=fav_barber_name,
        favorite_service_name=fav_svc_name,
    )


@router.get("/clients/paused-status")
async def get_paused_status(phone: str, db: BotDB, _auth: _BotAuth = None):
    phone = _normalize_phone(phone)
    org_id = settings.bot_organization_id
    client = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()
    return {"paused": client.bot_paused if client else False, "phone": phone}


# ---------------------------------------------------------------------------
# Disponibilidade
# ---------------------------------------------------------------------------


@router.get("/availability", response_model=AvailabilityOut)
async def get_availability(
    barber_id: int,
    service_id: int,
    date: date,
    db: BotDB,
) -> AvailabilityOut:
    org_id = settings.bot_organization_id
    unit_id = settings.bot_unit_id

    svc = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if not svc:
        raise HTTPException(404, "Serviço não encontrado")
    duration = svc.default_duration_min

    barber = (await db.execute(select(Barber).where(Barber.id == barber_id))).scalar_one_or_none()
    if not barber:
        raise HTTPException(404, "Barbeiro não encontrado")

    unit = (await db.execute(select(Unit).where(Unit.id == unit_id))).scalar_one_or_none()
    tz_name = unit.timezone if unit else "America/Sao_Paulo"
    tz = ZoneInfo(tz_name)

    # schema: weekday 0=Dom, 1=Seg, ..., 6=Sáb; Python weekday(): 0=Seg,...,6=Dom
    pg_weekday = (date.weekday() + 1) % 7

    bh_rows = (
        await db.execute(
            select(BusinessHours)
            .where(BusinessHours.unit_id == unit_id)
            .where(BusinessHours.weekday == pg_weekday)
        )
    ).scalars().all()

    if not bh_rows:
        return AvailabilityOut(
            date=date.isoformat(), barber_id=barber_id, barber_name=barber.name,
            service_duration_min=duration, slots=[],
        )

    bh = max(
        bh_rows,
        key=lambda x: (x.close_time.hour * 60 + x.close_time.minute)
        - (x.open_time.hour * 60 + x.open_time.minute),
    )

    # Gera candidatos de slots no fuso da unidade
    open_dt = datetime(date.year, date.month, date.day, bh.open_time.hour, bh.open_time.minute, tzinfo=tz)
    close_dt = datetime(date.year, date.month, date.day, bh.close_time.hour, bh.close_time.minute, tzinfo=tz)
    last_start = close_dt - timedelta(minutes=duration)

    candidates: List[datetime] = []
    cur = open_dt
    while cur <= last_start:
        candidates.append(cur)
        cur += timedelta(minutes=_SLOT_STEP)

    if not candidates:
        return AvailabilityOut(
            date=date.isoformat(), barber_id=barber_id, barber_name=barber.name,
            service_duration_min=duration, slots=[],
        )

    # Janela UTC do dia para consultas
    day_start_utc = open_dt.astimezone(timezone.utc)
    day_end_utc = (close_dt + timedelta(hours=1)).astimezone(timezone.utc)

    # Agendamentos existentes do barbeiro no dia (não cancelados)
    appts = (
        await db.execute(
            select(Appointment)
            .join(AppointmentItem, AppointmentItem.appointment_id == Appointment.id)
            .where(Appointment.organization_id == org_id)
            .where(AppointmentItem.barber_id == barber_id)
            .where(Appointment.start_at >= day_start_utc)
            .where(Appointment.start_at < day_end_utc)
            .where(Appointment.status != AppointmentStatus.cancelado)
        )
    ).scalars().all()

    # Folgas do barbeiro que cobrem o dia
    time_offs = (
        await db.execute(
            select(TimeOff)
            .where(TimeOff.barber_id == barber_id)
            .where(TimeOff.start_at < day_end_utc)
            .where(TimeOff.end_at > day_start_utc)
        )
    ).scalars().all()

    now_utc = datetime.now(timezone.utc)
    slots: List[Slot] = []

    for slot_start in candidates:
        slot_start_utc = slot_start.astimezone(timezone.utc)
        slot_end_utc = slot_start_utc + timedelta(minutes=duration)

        if slot_start_utc <= now_utc:
            continue
        if any(_overlaps(slot_start_utc, slot_end_utc, a.start_at, a.end_at) for a in appts):
            continue
        if any(_overlaps(slot_start_utc, slot_end_utc, t.start_at, t.end_at) for t in time_offs):
            continue

        local = slot_start.astimezone(tz)
        local_end = local + timedelta(minutes=duration)
        slots.append(
            Slot(
                start=local.strftime("%H:%M"),
                end=local_end.strftime("%H:%M"),
                start_iso=local.isoformat(),
            )
        )

    return AvailabilityOut(
        date=date.isoformat(),
        barber_id=barber_id,
        barber_name=barber.name,
        service_duration_min=duration,
        slots=slots,
    )


# ---------------------------------------------------------------------------
# Agendamentos
# ---------------------------------------------------------------------------


@router.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def create_appointment(body: AppointmentCreateIn, db: BotDB) -> AppointmentOut:
    org_id = settings.bot_organization_id
    unit_id = settings.bot_unit_id

    client = (await db.execute(select(Client).where(Client.id == body.client_id))).scalar_one_or_none()
    if not client or client.deleted_at is not None:
        raise HTTPException(404, "Cliente não encontrado")
    if client.is_blocked:
        raise HTTPException(403, "Cliente bloqueado — agendamento não permitido")

    barber = (await db.execute(select(Barber).where(Barber.id == body.barber_id))).scalar_one_or_none()
    if not barber or barber.deleted_at is not None:
        raise HTTPException(404, "Barbeiro não encontrado")

    svc = (await db.execute(select(Service).where(Service.id == body.service_id))).scalar_one_or_none()
    if not svc or not svc.is_active:
        raise HTTPException(404, "Serviço não encontrado")

    bs_link = (
        await db.execute(
            select(BarberService)
            .where(BarberService.barber_id == body.barber_id)
            .where(BarberService.service_id == body.service_id)
        )
    ).scalar_one_or_none()
    if not bs_link:
        raise HTTPException(422, "Este profissional não realiza este serviço")

    if body.start_at.tzinfo is None:
        raise HTTPException(422, "start_at deve incluir fuso horário (ex: 2026-06-05T09:00:00-03:00)")

    start_utc = body.start_at.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=svc.default_duration_min)

    if start_utc <= datetime.now(timezone.utc):
        raise HTTPException(422, "Horário já passou")

    # Validar horário comercial e alinhamento à grade
    unit = (await db.execute(select(Unit).where(Unit.id == unit_id))).scalar_one_or_none()
    tz_name = unit.timezone if unit else "America/Sao_Paulo"
    tz = ZoneInfo(tz_name)
    start_local = start_utc.astimezone(tz)
    pg_weekday = (start_local.weekday() + 1) % 7  # 0=Dom, 1=Seg ... 6=Sáb

    bh_for_day = (
        await db.execute(
            select(BusinessHours)
            .where(BusinessHours.unit_id == unit_id)
            .where(BusinessHours.weekday == pg_weekday)
        )
    ).scalars().all()

    if not bh_for_day:
        raise HTTPException(422, "Barbearia fechada neste dia da semana")

    bh = max(
        bh_for_day,
        key=lambda x: (x.close_time.hour * 60 + x.close_time.minute)
        - (x.open_time.hour * 60 + x.open_time.minute),
    )

    slot_h, slot_m = start_local.hour, start_local.minute
    open_h, open_m = bh.open_time.hour, bh.open_time.minute
    close_h, close_m = bh.close_time.hour, bh.close_time.minute

    if not (
        (open_h * 60 + open_m) <= (slot_h * 60 + slot_m) < (close_h * 60 + close_m)
    ):
        raise HTTPException(
            422,
            f"Horário fora do expediente — funcionamos das {bh.open_time.strftime('%Hh%M')} "
            f"às {bh.close_time.strftime('%Hh%M')}",
        )

    minutes_from_open = (slot_h * 60 + slot_m) - (open_h * 60 + open_m)
    if minutes_from_open % _SLOT_STEP != 0:
        raise HTTPException(
            422,
            f"Horário inválido — use intervalos de {_SLOT_STEP} minutos a partir das "
            f"{bh.open_time.strftime('%H:%M')} (ex: 09:00, 09:30, 10:00...)",
        )

    if await barber_has_conflict(db, body.barber_id, start_utc, end_utc):
        raise HTTPException(409, "Horário indisponível — conflito de agendamento ou folga")

    # display_number sequencial por unidade — advisory lock garante atomicidade
    # pg_advisory_xact_lock é liberado automaticamente ao fim da transação
    await db.execute(text(f"SELECT pg_advisory_xact_lock({unit_id})"))
    next_num = (
        await db.execute(
            select(func.coalesce(func.max(Appointment.display_number), 0) + 1)
            .where(Appointment.unit_id == unit_id)
        )
    ).scalar_one()

    appt = Appointment(
        organization_id=org_id,
        unit_id=unit_id,
        client_id=body.client_id,
        display_number=next_num,
        start_at=start_utc,
        end_at=end_utc,
        status=AppointmentStatus.agendado,
        booking_channel=ContactChannel.whatsapp,
        total_amount=svc.price,
    )
    db.add(appt)
    await db.flush()

    db.add(
        AppointmentItem(
            appointment_id=appt.id,
            service_id=svc.id,
            barber_id=barber.id,
            price_charged=svc.price,
            duration_minutes=svc.default_duration_min,
        )
    )

    # Avançar lead no funil para 'agendado' (se existir e ainda estiver em estágio ativo)
    _active_stages = {LeadStage.novo_contato, LeadStage.conversando}
    lead_row = (
        await db.execute(
            select(Lead)
            .where(Lead.client_id == body.client_id)
            .where(Lead.organization_id == org_id)
            .where(Lead.stage.in_(_active_stages))
            .order_by(Lead.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if lead_row is not None:
        old_stage = lead_row.stage
        lead_row.stage = LeadStage.agendado
        db.add(
            LeadEvent(
                lead_id=lead_row.id,
                organization_id=org_id,
                event_type="stage_changed",
                from_stage=old_stage,
                to_stage=LeadStage.agendado,
            )
        )

    return _appt_out(appt, barber.name, svc.name)


@router.get("/appointments", response_model=List[AppointmentOut])
async def list_appointments(
    phone: str,
    db: BotDB,
) -> list:
    phone = _normalize_phone(phone)
    org_id = settings.bot_organization_id

    client = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()

    if not client:
        return []

    appts = (
        await db.execute(
            select(Appointment)
            .where(Appointment.client_id == client.id)
            .where(Appointment.status == AppointmentStatus.agendado)
            .order_by(Appointment.start_at)
        )
    ).scalars().all()

    results = []
    for appt in appts:
        row = (
            await db.execute(
                select(Barber.name, Service.name)
                .select_from(AppointmentItem)
                .join(Barber, Barber.id == AppointmentItem.barber_id)
                .join(Service, Service.id == AppointmentItem.service_id)
                .where(AppointmentItem.appointment_id == appt.id)
                .limit(1)
            )
        ).first()
        barber_name = row[0] if row else "—"
        svc_name = row[1] if row else "—"
        results.append(_appt_out(appt, barber_name, svc_name))

    return results


@router.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment(
    appointment_id: int,
    db: BotDB,
    phone: str = Query(..., description="Telefone E.164 do solicitante (+5511999998888)"),
) -> AppointmentOut:
    phone = _normalize_phone(phone)
    org_id = settings.bot_organization_id

    owner = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()
    if not owner:
        raise HTTPException(404, "Cliente não encontrado para este telefone")

    appt = (
        await db.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .where(Appointment.client_id == owner.id)
        )
    ).scalar_one_or_none()

    if not appt:
        raise HTTPException(404, "Agendamento não encontrado para este cliente")
    if appt.status != AppointmentStatus.agendado:
        raise HTTPException(409, f"Agendamento não pode ser cancelado (status atual: {appt.status.value})")

    appt.status = AppointmentStatus.cancelado

    row = (
        await db.execute(
            select(Barber.name, Service.name)
            .select_from(AppointmentItem)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .join(Service, Service.id == AppointmentItem.service_id)
            .where(AppointmentItem.appointment_id == appt.id)
            .limit(1)
        )
    ).first()

    return _appt_out(appt, row[0] if row else "—", row[1] if row else "—")


@router.patch("/appointments/{appointment_id}/complete", response_model=AppointmentOut)
async def complete_appointment(
    appointment_id: int,
    db: BotDB,
) -> AppointmentOut:
    """Marca agendamento como concluído. Usado pela equipe após o atendimento."""
    appt = (
        await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    ).scalar_one_or_none()

    if not appt:
        raise HTTPException(404, "Agendamento não encontrado")
    if appt.status != AppointmentStatus.agendado:
        raise HTTPException(409, f"Só é possível concluir agendamentos com status 'agendado' (atual: {appt.status.value})")

    appt.status = AppointmentStatus.concluido
    # autoflush=False: sem flush as agregações do recalculate não veem este atendimento
    await db.flush()
    await _recalculate_loyalty(appt.client_id, settings.bot_organization_id, db)

    row = (
        await db.execute(
            select(Barber.name, Service.name)
            .select_from(AppointmentItem)
            .join(Barber, Barber.id == AppointmentItem.barber_id)
            .join(Service, Service.id == AppointmentItem.service_id)
            .where(AppointmentItem.appointment_id == appt.id)
            .limit(1)
        )
    ).first()

    return _appt_out(appt, row[0] if row else "—", row[1] if row else "—")
