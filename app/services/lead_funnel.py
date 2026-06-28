# file: app/services/lead_funnel.py
"""Avanço de estágio do funil no inbound — caminho ÚNICO, compartilhado.

Extraído de `app/api/bot.py` (era inline em `log_message`) para ser reusado pelo
webhook do Chatwoot (D-49) **sem duplicar** a transição de estágio — a Regra de Ouro
do CRM exige que o avanço continue num único lugar.

Comportamento idêntico ao que estava no bot:
- considera o lead ativo mais recente do cliente em `novo_contato`/`conversando`;
- atualiza `last_contact_at`/`updated_at`;
- se estiver em `novo_contato`, promove para `conversando` + grava `LeadEvent`.
NÃO cria lead (mantém o comportamento atual do bot).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Client, ClientConsent, Lead, LeadEvent
from models.enums import ConsentStatus, ContactChannel, LeadStage

_logger = logging.getLogger(__name__)

# Estágios considerados "lead ativo" (mesma definição usada no bot).
_ACTIVE_LEAD_STAGES = {LeadStage.novo_contato, LeadStage.conversando}
# Janela em que um lead ativo recente evita a criação de outro (cliente recorrente).
_RECENT_LEAD_DAYS = 7


async def _next_novo_contato_position(db: AsyncSession, org_id: int) -> int:
    """Posição (fim da coluna `novo_contato`) para um novo lead."""
    max_pos = (
        await db.execute(
            select(func.max(Lead.position)).where(
                Lead.organization_id == org_id,
                Lead.stage == LeadStage.novo_contato,
            )
        )
    ).scalar_one_or_none()
    return (max_pos + 1) if max_pos is not None else 0


async def _create_novo_contato_lead(
    db: AsyncSession, *, org_id: int, client: Client, phone: str,
    channel: ContactChannel, last_contact_at: Optional[datetime] = None,
) -> Lead:
    """Cria um Lead em `novo_contato` + LeadEvent('created'). Não faz commit."""
    lead = Lead(
        organization_id=org_id,
        client_id=client.id,
        name=client.name,
        phone_e164=phone,
        source=channel,
        stage=LeadStage.novo_contato,
        position=await _next_novo_contato_position(db, org_id),
        last_contact_at=last_contact_at,
    )
    db.add(lead)
    await db.flush()
    db.add(LeadEvent(
        lead_id=lead.id,
        organization_id=org_id,
        event_type="created",
        to_stage=LeadStage.novo_contato,
    ))
    return lead


async def upsert_client_and_lead(
    db: AsyncSession, *, org_id: int, phone: str, name: Optional[str],
    channel: ContactChannel = ContactChannel.whatsapp,
) -> Client:
    """Garante Client + Lead ativo para um contato. Caminho ÚNICO de criação.

    Mesma semântica de `POST /bot/clients` (upsert_client):
    - cliente novo: cria Client + ClientConsent(opt_in) + Lead(novo_contato);
    - cliente existente: atualiza o nome se o novo for mais informativo; cria
      Lead(novo_contato) se NÃO houver lead ativo (novo_contato/conversando) nos
      últimos 7 dias, senão só atualiza `last_contact_at` do lead recente.
    `name` pode ser None (1º contato sem nome → usa o telefone). Não faz commit.
    """
    now = datetime.now(timezone.utc)
    existing = (
        await db.execute(
            select(Client)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
        )
    ).scalar_one_or_none()

    if existing is not None:
        if name and len(name) > len(existing.name or ""):
            existing.name = name
        recent_lead = (
            await db.execute(
                select(Lead)
                .where(Lead.client_id == existing.id)
                .where(Lead.organization_id == org_id)
                .where(Lead.stage.in_(_ACTIVE_LEAD_STAGES))
                .where(Lead.created_at >= now - timedelta(days=_RECENT_LEAD_DAYS))
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent_lead is None:
            await _create_novo_contato_lead(
                db, org_id=org_id, client=existing, phone=phone,
                channel=channel, last_contact_at=now,
            )
        else:
            recent_lead.last_contact_at = now
            recent_lead.updated_at = now
        return existing

    client = Client(
        organization_id=org_id,
        name=name or phone,
        phone_e164=phone,
        acquisition_channel=channel,
    )
    db.add(client)
    await db.flush()
    db.add(ClientConsent(
        client_id=client.id,
        channel=channel,
        status=ConsentStatus.opt_in,
        source="chatbot_first_contact",
    ))
    await _create_novo_contato_lead(
        db, org_id=org_id, client=client, phone=phone, channel=channel,
    )
    return client


async def advance_lead_on_inbound(
    db: AsyncSession, *, org_id: int, client_id: int, now: datetime,
) -> Optional[Lead]:
    """Toca o lead ativo do cliente no inbound. Idempotente em estágio.

    Retorna o lead afetado (ou None se o cliente não tem lead em
    novo_contato/conversando). Não faz commit — o caller é dono da transação.
    """
    lead = (
        await db.execute(
            select(Lead)
            .where(Lead.client_id == client_id)
            .where(Lead.organization_id == org_id)
            .where(Lead.stage.in_({LeadStage.novo_contato, LeadStage.conversando}))
            .order_by(Lead.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if lead is None:
        return None

    lead.last_contact_at = now
    lead.updated_at = now
    if lead.stage == LeadStage.novo_contato:
        old_stage = lead.stage
        lead.stage = LeadStage.conversando
        db.add(
            LeadEvent(
                lead_id=lead.id,
                organization_id=org_id,
                event_type="stage_changed",
                from_stage=old_stage,
                to_stage=LeadStage.conversando,
            )
        )
        _logger.info("lead_id=%d stage novo_contato→conversando (inbound)", lead.id)
    return lead
