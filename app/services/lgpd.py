"""Direitos do titular — exportação e anonimização (Fase 8, ARQUITETURA_ALVO.md §1.11).

Ações **gestor-assistidas** (não há portal do cliente final para isto ainda —
D-79 entregou o site público, mas a sessão sem OTP não é identidade verificada,
então não se expõe art. 18 por lá): o titular pede por telefone/WhatsApp, o
gestor executa aqui. Cada ação é auditada (D-70).

**Cobertura (D-86).** Export e anonimização varrem TODAS as tabelas que guardam
dado pessoal do titular, não só `clients`: conversas do CRM, `message_log`,
leads e sessões do site. Anonimizar só a ficha deixava o titular identificável
pela própria conversa de WhatsApp — anonimização parcial não é anonimização.

O que sobrevive de propósito:
- `payments`/`appointment_items` — receita já reconhecida, sem PII;
- `consent_records` — é a **prova** do consentimento/revogação; apagá-la
  destruiria a defesa da própria organização numa fiscalização;
- `audit_logs` — append-only por desenho (D-70); pode conter nome antigo em
  `before`/`after` de edições anteriores. Débito consciente, ver DECISIONS D-86.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Appointment,
    Attachment,
    Client,
    ClientLoyalty,
    ClientMembership,
    ClientSession,
    ConsentRecord,
    Conversation,
    Lead,
    Message,
    MessageLog,
    Payment,
)

_ANONYMIZED_NAME = "Cliente anonimizado"
# Teto de linhas por coleção no export — alto o bastante para ser o histórico
# completo de um cliente real e baixo o bastante para não montar um JSON de
# centenas de MB. Quando estoura, o retorno diz explicitamente que truncou
# (o `LIMIT 500` silencioso anterior mentia por omissão).
_EXPORT_LIMIT = 5000


class ClientNotFound(Exception):
    def __init__(self, client_id: int) -> None:
        self.client_id = client_id
        super().__init__(f"Cliente {client_id} não encontrado")


def _collection(rows: list, mapper) -> dict:
    """Coleção do export com aviso explícito de truncamento."""
    truncated = len(rows) >= _EXPORT_LIMIT
    return {
        "total": len(rows),
        "truncado": truncated,
        "itens": [mapper(r) for r in rows],
    }


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
            .limit(_EXPORT_LIMIT)
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
    payments = (
        await db.execute(
            select(Payment)
            .join(Appointment, Appointment.id == Payment.appointment_id)
            .where(Appointment.client_id == client_id)
            .order_by(Payment.paid_at.desc())
            .limit(_EXPORT_LIMIT)
        )
    ).scalars().all()
    messages = (
        await db.execute(
            select(Message, Conversation.channel)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.client_id == client_id)
            .order_by(Message.created_at.desc())
            .limit(_EXPORT_LIMIT)
        )
    ).all()
    outbound = (
        await db.execute(
            select(MessageLog)
            .where(MessageLog.client_id == client_id)
            .order_by(MessageLog.created_at.desc())
            .limit(_EXPORT_LIMIT)
        )
    ).scalars().all()
    leads = (
        await db.execute(
            select(Lead).where(Lead.client_id == client_id).order_by(Lead.created_at.desc())
        )
    ).scalars().all()
    sessions = (
        await db.execute(
            select(ClientSession)
            .where(ClientSession.client_id == client_id)
            .order_by(ClientSession.created_at.desc())
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
            "foto_url": client.last_photo_url,
            "foto_descricao": client.last_photo_description,
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
        "agendamentos": _collection(
            list(appointments),
            lambda a: {
                "id": a.id,
                "inicio": a.start_at.isoformat(),
                "status": a.status.value,
                "valor_total": float(a.total_amount),
            },
        ),
        "pagamentos": _collection(
            list(payments),
            lambda p: {
                "id": p.id,
                "agendamento_id": p.appointment_id,
                "valor": float(p.amount),
                "gorjeta": float(p.tip_amount) if p.tip_amount is not None else None,
                "forma": p.method.value,
                "pago_em": p.paid_at.isoformat(),
            },
        ),
        "assinaturas": _collection(
            list(memberships),
            lambda m: {
                "id": m.id,
                "status": m.status.value,
                "vigencia_inicio": m.start_at.isoformat(),
                "vigencia_fim": m.end_at.isoformat(),
                "preco_pago": float(m.price_paid),
            },
        ),
        "conversas": _collection(
            list(messages),
            lambda row: {
                "canal": row[1].value,
                "remetente": row[0].sender_type.value,
                "tipo": row[0].message_type.value,
                "texto": row[0].body_text,
                "em": row[0].created_at.isoformat(),
            },
        ),
        "mensagens_enviadas": _collection(
            list(outbound),
            lambda m: {
                "template": m.template,
                "texto": m.body_text,
                "status_entrega": m.delivery_status.value,
                "em": m.created_at.isoformat(),
            },
        ),
        "leads": _collection(
            list(leads),
            lambda lead: {
                "id": lead.id,
                "nome": lead.name,
                "telefone": lead.phone_e164,
                "estagio": lead.stage.value,
                "observacoes": lead.notes,
                "criado_em": lead.created_at.isoformat(),
            },
        ),
        "sessoes_site": _collection(
            list(sessions),
            lambda s: {
                "criada_em": s.created_at.isoformat(),
                "ultimo_acesso": s.last_seen_at.isoformat(),
                "dispositivo": s.device_label or s.user_agent,
                "ip": s.ip,
                "revogada_em": s.revoked_at.isoformat() if s.revoked_at else None,
            },
        ),
        "consentimentos": _collection(
            list(consents),
            lambda c: {
                "canal": c.channel,
                "status": c.status,
                "origem": c.source,
                "versao_politica": c.policy_version,
                "em": c.created_at.isoformat(),
            },
        ),
    }


async def anonymize_client(db: AsyncSession, client_id: int) -> Client:
    """Remove o PII do titular em todas as tabelas que o guardam, preservando
    agregados financeiros (`Payment`/`AppointmentItem` intocados — a receita já
    reconhecida não deve sumir do relatório) e a prova de consentimento
    (`consent_records`). Telefone vira um placeholder sintético (não pode ser
    NULL/vazio: `CHECK` de formato + `UNIQUE` por org)."""
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if client is None:
        raise ClientNotFound(client_id)

    now = datetime.now(timezone.utc)
    placeholder_phone = f"+{1_000_000_000 + client.id}"

    client.name = _ANONYMIZED_NAME
    client.phone_e164 = placeholder_phone
    client.email = None
    client.birth_date = None
    client.notes = None
    client.last_photo_url = None
    client.last_photo_description = None
    client.anonymized_at = now

    # Conversas do CRM: o telefone é a chave natural (UNIQUE org+phone+channel),
    # por isso vira o mesmo placeholder em vez de NULL.
    conv_ids = (
        await db.execute(select(Conversation.id).where(Conversation.client_id == client_id))
    ).scalars().all()
    if conv_ids:
        await db.execute(
            update(Conversation)
            .where(Conversation.id.in_(conv_ids))
            .values(phone_e164=placeholder_phone, last_message_preview=None, updated_at=now)
        )
        msg_ids = (
            await db.execute(select(Message.id).where(Message.conversation_id.in_(conv_ids)))
        ).scalars().all()
        if msg_ids:
            await db.execute(
                update(Message).where(Message.id.in_(msg_ids)).values(body_text=None)
            )
            await db.execute(
                update(Attachment)
                .where(Attachment.message_id.in_(msg_ids))
                .values(url=None, transcript=None, caption=None)
            )

    # Mensagens enviadas pelo sistema (lembrete/reativação): o corpo carrega o
    # nome do titular.
    await db.execute(
        update(MessageLog).where(MessageLog.client_id == client_id).values(body_text=None)
    )

    await db.execute(
        update(Lead)
        .where(Lead.client_id == client_id)
        .values(name=_ANONYMIZED_NAME, phone_e164=None, notes=None, updated_at=now)
    )

    # Sessões do site: revogar (o titular pediu esquecimento — manter um cookie
    # válido apontando para a ficha seria contraditório) e limpar IP/dispositivo.
    await db.execute(
        update(ClientSession)
        .where(ClientSession.client_id == client_id)
        .values(
            revoked_at=func.coalesce(ClientSession.revoked_at, now),
            ip=None,
            user_agent=None,
            device_label=None,
        )
    )

    await db.flush()
    return client
