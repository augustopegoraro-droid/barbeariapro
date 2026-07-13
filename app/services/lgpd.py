"""Direitos do titular — exportação e anonimização (Fase 8, ARQUITETURA_ALVO.md §1.11).

Ações **gestor-assistidas** (não há site público/portal do cliente final ainda —
D-73/`promptsitepublico.md`): o titular pede por telefone/WhatsApp, o gestor
executa aqui. Cada ação é auditada (D-70).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Appointment,
    Client,
    ClientLoyalty,
    ClientMembership,
    ConsentRecord,
)

_ANONYMIZED_NAME = "Cliente anonimizado"


class ClientNotFound(Exception):
    def __init__(self, client_id: int) -> None:
        self.client_id = client_id
        super().__init__(f"Cliente {client_id} não encontrado")


async def export_client_data(db: AsyncSession, client_id: int) -> dict:
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if client is None:
        raise ClientNotFound(client_id)

    loyalty = (
        await db.execute(select(ClientLoyalty).where(ClientLoyalty.client_id == client_id))
    ).scalar_one_or_none()
    appointments = (
        await db.execute(
            select(Appointment)
            .where(Appointment.client_id == client_id)
            .order_by(Appointment.start_at.desc())
            .limit(500)
        )
    ).scalars().all()
    memberships = (
        await db.execute(select(ClientMembership).where(ClientMembership.client_id == client_id))
    ).scalars().all()
    consents = (
        await db.execute(
            select(ConsentRecord)
            .where(ConsentRecord.subject_type == "client")
            .where(ConsentRecord.subject_id == client_id)
            .order_by(ConsentRecord.created_at.desc())
        )
    ).scalars().all()

    return {
        "cliente": {
            "id": client.id,
            "nome": client.name,
            "telefone": client.phone_e164,
            "email": client.email,
            "data_nascimento": client.birth_date.isoformat() if client.birth_date else None,
            "observacoes": client.notes,
            "canal_aquisicao": client.acquisition_channel.value if client.acquisition_channel else None,
            "cadastrado_em": client.created_at.isoformat(),
            "bloqueado": client.is_blocked,
            "anonimizado_em": client.anonymized_at.isoformat() if client.anonymized_at else None,
        },
        "fidelidade": (
            {
                "nivel": loyalty.nivel.value,
                "status": loyalty.status.value,
                "visitas": loyalty.visit_count,
                "total_gasto": float(loyalty.total_spent),
            }
            if loyalty
            else None
        ),
        "agendamentos": [
            {
                "id": a.id,
                "inicio": a.start_at.isoformat(),
                "status": a.status.value,
                "valor_total": float(a.total_amount),
            }
            for a in appointments
        ],
        "assinaturas": [
            {
                "id": m.id,
                "status": m.status.value,
                "vigencia_inicio": m.start_at.isoformat(),
                "vigencia_fim": m.end_at.isoformat(),
                "preco_pago": float(m.price_paid),
            }
            for m in memberships
        ],
        "consentimentos": [
            {
                "canal": c.channel,
                "status": c.status,
                "origem": c.source,
                "em": c.created_at.isoformat(),
            }
            for c in consents
        ],
    }


async def anonymize_client(db: AsyncSession, client_id: int) -> Client:
    """Remove o PII do cliente (nome/telefone/email/nascimento/observações/fotos),
    preservando agregados financeiros (Payment/AppointmentItem intocados — a
    receita já reconhecida não deve sumir do relatório). Telefone vira um
    placeholder sintético (não pode ser NULL/vazio: `CHECK` de formato +
    `UNIQUE` por org)."""
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if client is None:
        raise ClientNotFound(client_id)

    client.name = _ANONYMIZED_NAME
    client.phone_e164 = f"+{1_000_000_000 + client.id}"
    client.email = None
    client.birth_date = None
    client.notes = None
    client.last_photo_url = None
    client.last_photo_description = None
    client.anonymized_at = datetime.now(timezone.utc)
    await db.flush()
    return client
