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
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Lead, LeadEvent
from models.enums import LeadStage

_logger = logging.getLogger(__name__)


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
