"""Testes unitários do webhook do Chatwoot — funções puras de parse, sem banco.

Cobrem `parse_chatwoot_message` e os helpers de extração (D-49, Fase 4 esqueleto).
O endpoint completo (com DB/RLS) é de integração e fica para a suíte com seed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.enums import MessageSenderType


# ────────────────────────────────────────────────────────────
# parse_chatwoot_message — evento e direção
# ────────────────────────────────────────────────────────────

def _incoming_payload(**over):
    base = {
        "event": "message_created",
        "id": 9001,
        "content": "bom dia, queria agendar",
        "message_type": "incoming",
        "conversation": {"id": 45, "status": "open"},
        "sender": {"type": "contact", "phone_number": "+5563999368196", "name": "João"},
        "account": {"id": 1},
    }
    base.update(over)
    return base


def test_parse_ignores_non_message_event():
    from app.api.chatwoot import parse_chatwoot_message
    assert parse_chatwoot_message({"event": "conversation_created"}) is None
    assert parse_chatwoot_message({"event": "webwidget_triggered"}) is None


def test_parse_incoming_contact_message():
    from app.api.chatwoot import parse_chatwoot_message
    p = parse_chatwoot_message(_incoming_payload())
    assert p is not None
    assert p.sender_type == MessageSenderType.client
    assert p.is_incoming is True
    assert p.raw_phone == "+5563999368196"
    assert p.body == "bom dia, queria agendar"
    assert p.chatwoot_message_id == "9001"   # sempre string p/ idempotência
    assert p.conversation_id == 45
    assert p.conversation_status == "open"


def test_parse_outgoing_agent_bot_is_bot():
    from app.api.chatwoot import parse_chatwoot_message
    p = parse_chatwoot_message(_incoming_payload(
        message_type="outgoing",
        sender={"type": "agent_bot", "name": "Raquel"},
    ))
    assert p.sender_type == MessageSenderType.bot
    assert p.is_incoming is False


def test_parse_outgoing_human_user_is_human():
    from app.api.chatwoot import parse_chatwoot_message
    p = parse_chatwoot_message(_incoming_payload(
        message_type="outgoing",
        sender={"type": "user", "name": "Atendente", "phone_number": None},
    ))
    assert p.sender_type == MessageSenderType.human
    assert p.is_incoming is False


def test_parse_message_type_as_int():
    """Versões do Chatwoot enviam message_type como 0 (incoming) / 1 (outgoing)."""
    from app.api.chatwoot import parse_chatwoot_message
    assert parse_chatwoot_message(_incoming_payload(message_type=0)).is_incoming is True
    assert parse_chatwoot_message(_incoming_payload(message_type=1)).is_incoming is False


def test_parse_missing_id_yields_none_idempotency_key():
    from app.api.chatwoot import parse_chatwoot_message
    payload = _incoming_payload()
    del payload["id"]
    assert parse_chatwoot_message(payload).chatwoot_message_id is None


# ────────────────────────────────────────────────────────────
# Extração de telefone (sender → fallback conversation.meta.sender)
# ────────────────────────────────────────────────────────────

def test_extract_phone_from_sender():
    from app.api.chatwoot import _extract_phone_raw
    assert _extract_phone_raw(_incoming_payload()) == "+5563999368196"


def test_extract_phone_fallback_to_conversation_meta():
    from app.api.chatwoot import _extract_phone_raw
    payload = _incoming_payload(
        sender={"type": "contact", "name": "João"},  # sem phone_number
        conversation={"id": 45, "status": "open",
                      "meta": {"sender": {"phone_number": "+5563988887777"}}},
    )
    assert _extract_phone_raw(payload) == "+5563988887777"


def test_extract_phone_none_when_absent():
    from app.api.chatwoot import _extract_phone_raw
    payload = _incoming_payload(sender={"type": "contact"}, conversation={"id": 1})
    assert _extract_phone_raw(payload) is None


# ────────────────────────────────────────────────────────────
# _resolve_sender — fallback pela direção quando sender.type ausente
# ────────────────────────────────────────────────────────────

def test_resolve_sender_fallback_incoming_is_client():
    from app.api.chatwoot import _resolve_sender
    stype, incoming = _resolve_sender({"message_type": "incoming", "sender": {}})
    assert stype == MessageSenderType.client and incoming is True


def test_resolve_sender_fallback_outgoing_is_human():
    from app.api.chatwoot import _resolve_sender
    stype, incoming = _resolve_sender({"message_type": "outgoing", "sender": {}})
    assert stype == MessageSenderType.human and incoming is False


def test_resolve_sender_type_overrides_direction():
    """sender.type=agent_bot manda, mesmo com message_type outgoing."""
    from app.api.chatwoot import _resolve_sender
    stype, _ = _resolve_sender({"message_type": "outgoing", "sender": {"type": "agent_bot"}})
    assert stype == MessageSenderType.bot


# ────────────────────────────────────────────────────────────
# Regressão: o helper de funil compartilhado existe e o bot o usa
# ────────────────────────────────────────────────────────────

def test_lead_funnel_helper_signature():
    import inspect
    from app.services.lead_funnel import advance_lead_on_inbound
    params = list(inspect.signature(advance_lead_on_inbound).parameters)
    assert params[0] == "db"
    assert {"org_id", "client_id", "now"}.issubset(set(params))


def test_bot_uses_shared_funnel_helper():
    """bot.py deve importar o helper compartilhado (não duplicar a transição)."""
    import app.api.bot as bot_module
    assert hasattr(bot_module, "advance_lead_on_inbound")


def test_chatwoot_router_registered():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/chatwoot/webhook" in paths
