"""
Testes unitários do serviço de lembretes — funções puras, sem banco.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from zoneinfo import ZoneInfo


# ────────────────────────────────────────────────────────────
# idempotency_key
# ────────────────────────────────────────────────────────────

def test_idempotency_key_por_agendamento():
    from app.services.reminders import idempotency_key
    assert idempotency_key(42) == "reminder_24h_v1:42"
    assert idempotency_key(42) == idempotency_key(42)
    assert idempotency_key(1) != idempotency_key(2)


# ────────────────────────────────────────────────────────────
# build_message
# ────────────────────────────────────────────────────────────

def _local(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/Sao_Paulo"))


def test_build_message_completa():
    from app.services.reminders import build_message
    msg = build_message(
        client_name="João Silva",
        start_local=_local(2026, 6, 12, 14, 30),  # sexta-feira
        service_name="Corte",
        barber_name="Taylor",
    )
    assert "Oi João!" in msg
    assert "14:30" in msg
    assert "sexta" in msg
    assert "*Corte*" in msg
    assert "Taylor" in msg
    assert "SIM" in msg


def test_build_message_sem_servico_e_barbeiro():
    from app.services.reminders import build_message
    msg = build_message(
        client_name="Maria",
        start_local=_local(2026, 6, 13, 9, 0),  # sábado
        service_name=None,
        barber_name=None,
    )
    assert "Oi Maria!" in msg
    assert "09:00" in msg
    assert "sábado" in msg
    assert "com o" not in msg
    assert "para *" not in msg


def test_build_message_nome_vazio():
    from app.services.reminders import build_message
    msg = build_message(
        client_name="",
        start_local=_local(2026, 6, 12, 10, 0),
        service_name="Barba",
        barber_name="Thedy",
    )
    assert "Oi cliente!" in msg
