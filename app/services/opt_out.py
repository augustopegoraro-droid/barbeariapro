# file: app/services/opt_out.py
"""Opt-out de mensagens automáticas por palavra-chave (WhatsApp).

Quando o cliente responde SAIR/PARAR/etc. a uma mensagem, grava (upsert)
`ConsentStatus.opt_out` no canal WhatsApp. Isso já barra lembrete
(`reminders.py`) e reativação (`reactivation.py`), que filtram por esse consent
antes de enviar. Fecha a lacuna de conformidade: dar ao cliente uma forma
explícita de parar de receber mensagens proativas (exigência de boas práticas
da Meta e o que mais reduz denúncia).
"""
from __future__ import annotations

import logging
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import Client, ClientConsent, ConsentStatus, ContactChannel

_logger = logging.getLogger(__name__)

# Match EXATO (após normalização) para evitar falso positivo — "vou ter que
# cancelar meu horário" NÃO deve descadastrar. Só conta a mensagem que é
# essencialmente a palavra-chave. Padrão de mercado (SAIR/PARAR/STOP).
_OPT_OUT_KEYWORDS: frozenset[str] = frozenset(
    {
        "sair",
        "parar",
        "pare",
        "parar de receber",
        "nao quero receber",
        "nao quero mais receber",
        "nao quero mais mensagens",
        "descadastrar",
        "cancelar inscricao",
        "sair da lista",
        "remover meu numero",
        "stop",
        "unsubscribe",
    }
)

# Confirmação enviada 1x quando o opt-out é registrado (o cliente sabe que
# funcionou — sem isso ele repete ou denuncia).
CONFIRMATION = (
    "Pronto! ✅ Não vou mais te enviar mensagens automáticas. "
    "Se um dia quiser voltar a receber, é só me avisar por aqui. 🙂"
)


def _normalize(text: str) -> str:
    """lower + remove acentos + tira pontuação/emoji das bordas + colapsa espaços."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = text.strip(" .!?,;:*\n\t\"'-")
    return " ".join(text.split())


def is_opt_out_keyword(body: str | None) -> bool:
    """True se a mensagem é (essencialmente) uma palavra-chave de descadastro."""
    if not body:
        return False
    return _normalize(body) in _OPT_OUT_KEYWORDS


async def register_opt_out(
    session: AsyncSession, *, org_id: int, phone: str
) -> int | None:
    """Grava (upsert) opt-out no canal WhatsApp para o cliente do telefone.

    Vira o status se já existir consent (UNIQUE client_id+channel). Retorna o
    ``client_id``, ou ``None`` se não houver Client com esse número (nada a
    descadastrar — lembrete/reativação só disparam para Client existente).
    Requer a sessão já com o tenant/RLS setado.
    """
    client_id = (
        await session.execute(
            select(Client.id)
            .where(Client.organization_id == org_id)
            .where(Client.phone_e164 == phone)
            .limit(1)
        )
    ).scalar_one_or_none()
    if client_id is None:
        return None

    await session.execute(
        pg_insert(ClientConsent)
        .values(
            client_id=client_id,
            channel=ContactChannel.whatsapp,
            status=ConsentStatus.opt_out,
            source="wa_keyword",
        )
        .on_conflict_do_update(
            constraint="client_consents_unique",
            set_={
                "status": ConsentStatus.opt_out,
                "source": "wa_keyword",
                "updated_at": func.now(),
            },
        )
    )
    return client_id
