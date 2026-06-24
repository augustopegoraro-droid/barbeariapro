"""APIs de leitura do CRM conversacional — Fase 3.

Lista de conversas paginada por cursor, scroll de mensagens por cursor e
busca full-text via pg_trgm. Apenas leitura; escrita está em
app/services/conversation.py + app/api/bot.py.
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import Annotated, Any, AsyncIterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status as http_status
from fastapi.responses import StreamingResponse
from jose import JWTError
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.rbac import require_full_access
from app.core.security import decode_access_token
from app.deps import get_current_user, get_tenant_db, resolve_current_role
from app.services import conversation as _conv_svc
from app.services import sse_broker
from app.services import whatsapp
from models import Client, Conversation, Lead, Message, User
from models.enums import ConversationStatus, MessageSenderType, MessageType

router = APIRouter(prefix="/crm", tags=["crm"])

_DEFAULT_LIST_LIMIT = 20
_DEFAULT_MSG_LIMIT = 50
_MAX_LIMIT = 200


# ─────────────────────────── Schemas de saída ───────────────────────────────

class AttachmentOut(BaseModel):
    id: int
    media_type: str
    url: Optional[str]
    mime: Optional[str]
    transcript: Optional[str]
    caption: Optional[str]
    duration_s: Optional[int]


class MessageOut(BaseModel):
    id: int
    sender_type: str
    message_type: str
    body: Optional[str]
    wa_message_id: Optional[str]
    created_at: str
    attachments: List[AttachmentOut]


class ConversationOut(BaseModel):
    id: int
    phone: str
    channel: str
    status: str
    bot_active: bool
    unread_count: int
    last_message_at: Optional[str]
    last_message_preview: Optional[str]
    client_id: Optional[int]
    client_name: Optional[str]
    lead_id: Optional[int]
    lead_stage: Optional[str]
    assigned_user_id: Optional[int]


class ConversationListOut(BaseModel):
    items: List[ConversationOut]
    next_cursor: Optional[str]
    total_open: int


class MessagePageOut(BaseModel):
    items: List[MessageOut]
    has_more: bool


class SearchResultOut(BaseModel):
    message_id: int
    conversation_id: int
    phone: str
    sender_type: str
    body: str
    created_at: str


# ─────────────────────────── Helpers ─────────────────────────────────────────

def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _encode_cursor(last_message_at: Optional[datetime], conv_id: int) -> str:
    ts = last_message_at.isoformat() if last_message_at else ""
    raw = json.dumps({"ts": ts, "id": conv_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[Optional[datetime], int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(raw)
        ts = datetime.fromisoformat(data["ts"]) if data["ts"] else None
        return ts, int(data["id"])
    except Exception:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cursor inválido",
        )


def _msg_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        sender_type=m.sender_type.value,
        message_type=m.message_type.value,
        body=m.body_text,
        wa_message_id=m.wa_message_id,
        created_at=_iso(m.created_at),
        attachments=[
            AttachmentOut(
                id=a.id,
                media_type=a.media_type.value,
                url=a.url,
                mime=a.mime,
                transcript=a.transcript,
                caption=a.caption,
                duration_s=a.duration_s,
            )
            for a in m.attachments
        ],
    )


# ─────────────────────────── Endpoints ──────────────────────────────────────

@router.get("/conversations", response_model=ConversationListOut)
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    status: Optional[str] = Query(None, description="open | snoozed | closed"),
    cursor: Optional[str] = Query(None),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIMIT),
) -> ConversationListOut:
    """Lista conversas ordenadas por última mensagem (mais recente primeiro).

    Usa cursor-based pagination: passe `next_cursor` da resposta anterior.
    """
    require_full_access(await resolve_current_role(db, current_user))

    total_open = (
        await db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.status == ConversationStatus.open
            )
        )
    ).scalar_one()

    # JOIN para trazer client_name e lead_stage numa única query
    q = (
        select(
            Conversation,
            Client.name.label("client_name"),
            Lead.stage.label("lead_stage"),
        )
        .outerjoin(Client, Client.id == Conversation.client_id)
        .outerjoin(Lead, Lead.id == Conversation.lead_id)
        .order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.id.desc(),
        )
    )

    if status:
        try:
            q = q.where(Conversation.status == ConversationStatus(status))
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Status inválido: {status!r}",
            )

    if cursor:
        cursor_ts, cursor_id = _decode_cursor(cursor)
        if cursor_ts:
            q = q.where(
                (Conversation.last_message_at < cursor_ts)
                | (
                    (Conversation.last_message_at == cursor_ts)
                    & (Conversation.id < cursor_id)
                )
            )
        else:
            q = q.where(Conversation.id < cursor_id)

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).all()

    has_more = len(rows) > limit
    page = rows[:limit]

    next_cursor: Optional[str] = None
    if has_more and page:
        last_conv = page[-1][0]
        next_cursor = _encode_cursor(last_conv.last_message_at, last_conv.id)

    items = [
        ConversationOut(
            id=conv.id,
            phone=conv.phone_e164,
            channel=conv.channel.value,
            status=conv.status.value,
            bot_active=conv.bot_active,
            unread_count=conv.unread_count,
            last_message_at=_iso(conv.last_message_at),
            last_message_preview=conv.last_message_preview,
            client_id=conv.client_id,
            client_name=client_name,
            lead_id=conv.lead_id,
            lead_stage=lead_stage.value if lead_stage else None,
            assigned_user_id=conv.assigned_user_id,
        )
        for conv, client_name, lead_stage in page
    ]

    return ConversationListOut(items=items, next_cursor=next_cursor,
                               total_open=total_open)


@router.get("/conversations/search", response_model=List[SearchResultOut])
async def search_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    q: str = Query(..., min_length=2, description="Termo de busca"),
    limit: int = Query(20, ge=1, le=100),
) -> List[SearchResultOut]:
    """Busca full-text em body_text (pg_trgm ILIKE, índice GIN).

    Retorna mensagens mais recentes que batem o termo, com conversation_id
    e phone para o frontend abrir o drawer correto.
    """
    require_full_access(await resolve_current_role(db, current_user))

    rows = (
        await db.execute(
            select(Message, Conversation.phone_e164)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.body_text.ilike(f"%{q}%"))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).all()

    return [
        SearchResultOut(
            message_id=m.id,
            conversation_id=m.conversation_id,
            phone=phone,
            sender_type=m.sender_type.value,
            body=m.body_text or "",
            created_at=_iso(m.created_at),
        )
        for m, phone in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ConversationOut:
    require_full_access(await resolve_current_role(db, current_user))

    row = (
        await db.execute(
            select(
                Conversation,
                Client.name.label("client_name"),
                Lead.stage.label("lead_stage"),
            )
            .outerjoin(Client, Client.id == Conversation.client_id)
            .outerjoin(Lead, Lead.id == Conversation.lead_id)
            .where(Conversation.id == conversation_id)
        )
    ).first()

    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                            detail="Conversa não encontrada")

    conv, client_name, lead_stage = row
    return ConversationOut(
        id=conv.id,
        phone=conv.phone_e164,
        channel=conv.channel.value,
        status=conv.status.value,
        bot_active=conv.bot_active,
        unread_count=conv.unread_count,
        last_message_at=_iso(conv.last_message_at),
        last_message_preview=conv.last_message_preview,
        client_id=conv.client_id,
        client_name=client_name,
        lead_id=conv.lead_id,
        lead_stage=lead_stage.value if lead_stage else None,
        assigned_user_id=conv.assigned_user_id,
    )


@router.get(
    "/conversations/{conversation_id}/messages", response_model=MessagePageOut
)
async def get_conversation_messages(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    before: Optional[int] = Query(
        None,
        description="ID da mensagem mais antiga já carregada (scroll infinito p/ cima)",
    ),
    limit: int = Query(_DEFAULT_MSG_LIMIT, ge=1, le=_MAX_LIMIT),
) -> MessagePageOut:
    """Scroll de mensagens por cursor.

    Sem `before`: retorna as últimas `limit` mensagens (abertura do drawer).
    Com `before=<id>`: retorna até `limit` mensagens anteriores a esse ID
    (scroll infinito para cima). Resultado em ordem cronológica ascendente.
    """
    require_full_access(await resolve_current_role(db, current_user))

    exists = (
        await db.execute(
            select(Conversation.id).where(Conversation.id == conversation_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                            detail="Conversa não encontrada")

    q = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(selectinload(Message.attachments))
        .order_by(Message.created_at.desc(), Message.id.desc())
    )
    if before is not None:
        q = q.where(Message.id < before)

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    page = list(reversed(rows[:limit]))   # ordem cronológica para o frontend

    return MessagePageOut(items=[_msg_out(m) for m in page], has_more=has_more)


@router.patch("/conversations/{conversation_id}/read", status_code=200)
async def mark_conversation_read(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> dict:
    """Zera unread_count ao abrir o drawer (marcar como lida)."""
    require_full_access(await resolve_current_role(db, current_user))
    conv = (
        await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                            detail="Conversa não encontrada")
    conv.unread_count = 0
    conv.updated_at = datetime.now(timezone.utc)
    return {"ok": True}


# ─────────────────────────── Envio de mensagem ───────────────────────────────

class SendMessageIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=4096)


@router.post("/conversations/{conversation_id}/send",
             response_model=MessageOut,
             status_code=http_status.HTTP_201_CREATED)
async def send_conversation_message(
    conversation_id: int,
    body: SendMessageIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MessageOut:
    """Envia mensagem pelo CRM (atendente humano → WhatsApp).

    Em staging (Evolution não configurado) grava sem disparar — permite
    testar a UI sem WhatsApp real.
    Em produção, falha com 502 se a Evolution API não aceitar.
    """
    require_full_access(await resolve_current_role(db, current_user))

    conv = (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                            detail="Conversa não encontrada")

    evolution_configured = bool(
        settings.evolution_api_url and settings.evolution_instance_name
    )
    if evolution_configured:
        sent = await whatsapp.send_text(conv.phone_e164, body.body)
        if not sent:
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Falha ao enviar mensagem via WhatsApp.",
            )

    msg = await _conv_svc.record_message(
        db,
        org_id=conv.organization_id,
        phone=conv.phone_e164,
        sender_type=MessageSenderType.human,
        body=body.body,
        message_type=MessageType.text,
        sender_user_id=current_user.id,
    )
    if msg is None:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mensagem não pôde ser registrada.",
        )
    await db.commit()

    # Retorna sem acessar msg.attachments (lazy-load inválido pós-commit).
    # Mensagens humanas nunca têm anexo via esta rota.
    return MessageOut(
        id=msg.id,
        sender_type=msg.sender_type.value,
        message_type=msg.message_type.value,
        body=msg.body_text,
        wa_message_id=msg.wa_message_id,
        created_at=_iso(msg.created_at) or datetime.now(timezone.utc).isoformat(),
        attachments=[],
    )


@router.get("/stream")
async def sse_stream(
    request: Request,
    token: str = Query(..., description="JWT token (EventSource não suporta headers)"),
) -> StreamingResponse:
    """SSE stream de mensagens em tempo real para a org do usuário autenticado."""
    try:
        payload = decode_access_token(token)
        org_id = int(payload["org"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED,
                            detail="Token inválido")

    async def generator() -> AsyncIterator[str]:
        q = sse_broker.subscribe(org_id)
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sse_broker.unsubscribe(org_id, q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
