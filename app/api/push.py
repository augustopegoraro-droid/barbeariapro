# file: app/api/push.py
"""Notificações push da EQUIPE (subscrição self-service) + cron interno de
lembretes "de última hora" (cliente + profissional, 30min por padrão).

A subscrição do CLIENTE final vive em `app/api/public.py` (auth por cookie de
sessão, D-79) — este módulo cobre só o lado do usuário autenticado (JWT).
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_bot_db, get_bot_org_id, get_current_user, get_tenant_db
from app.services import push as push_svc
from models import PushSubscriberType, PushSubscription, User

router = APIRouter(prefix="/notificacoes/push", tags=["notificacoes"])
internal_router = APIRouter(prefix="/internal/push", tags=["push-internal"])

CurrentUser = Annotated[User, Depends(get_current_user)]
TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
BotDB = Annotated[AsyncSession, Depends(get_bot_db)]
BotOrgId = Annotated[int, Depends(get_bot_org_id)]


class SubscribeIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    user_agent: Optional[str] = None


@router.post("/subscription", status_code=http_status.HTTP_204_NO_CONTENT)
async def subscribe(body: SubscribeIn, user: CurrentUser, db: TenantDB) -> None:
    await db.execute(
        pg_insert(PushSubscription)
        .values(
            organization_id=user.organization_id,
            subscriber_type=PushSubscriberType.user,
            user_id=user.id,
            client_id=None,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth_key=body.auth,
            user_agent=body.user_agent,
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={
                "user_id": user.id,
                "client_id": None,
                "subscriber_type": PushSubscriberType.user,
                "p256dh": body.p256dh,
                "auth_key": body.auth,
                "user_agent": body.user_agent,
                "revoked_at": None,
            },
        )
    )
    await db.commit()


class UnsubscribeIn(BaseModel):
    endpoint: str


@router.delete("/subscription", status_code=http_status.HTTP_204_NO_CONTENT)
async def unsubscribe(body: UnsubscribeIn, user: CurrentUser, db: TenantDB) -> None:
    row = (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == body.endpoint,
                PushSubscription.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Subscrição não encontrada.")
    await db.execute(
        update(PushSubscription)
        .where(PushSubscription.id == row.id)
        .values(revoked_at=func.now())
    )
    await db.commit()


class NearRemindersOut(BaseModel):
    sent: int
    skipped: int
    total_targets: int


@internal_router.post("/near-reminders/run", response_model=NearRemindersOut)
async def run_near_reminders(db: BotDB, org_id: BotOrgId) -> NearRemindersOut:
    """Lembretes push "de última hora" (cliente + profissional).

    Chamado por um cron novo do n8n a cada ~10min (auth via X-Bot-Token) —
    cadência mais fina que o `/internal/reminders/run` de 24h existente.
    """
    result = await push_svc.run_near_reminders(org_id=org_id, session=db)
    return NearRemindersOut(**result)
