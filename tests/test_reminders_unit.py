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
    start = datetime(2026, 6, 13, 14, 0)
    assert idempotency_key(42, start) == "reminder_24h_v1:42:20260613T1400"
    assert idempotency_key(42, start) == idempotency_key(42, start)
    assert idempotency_key(1, start) != idempotency_key(2, start)


def test_idempotency_key_muda_apos_remarcacao():
    from app.services.reminders import idempotency_key
    original = datetime(2026, 6, 13, 14, 0)
    remarcado = datetime(2026, 6, 19, 10, 30)
    assert idempotency_key(42, original) != idempotency_key(42, remarcado)


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


def test_build_message_identifica_remetente():
    from app.services.reminders import build_message
    msg = build_message(
        client_name="João Silva",
        start_local=_local(2026, 6, 12, 14, 30),
        service_name="Corte",
        barber_name="Taylor",
        business_name="Taylor & Thedy",
    )
    assert "Aqui é da *Taylor & Thedy*" in msg
    assert "Oi João!" in msg
    assert "SIM" in msg
    # sem business_name → não injeta a linha de identificação
    sem = build_message(
        client_name="João",
        start_local=_local(2026, 6, 12, 14, 30),
        service_name="Corte",
        barber_name="Taylor",
    )
    assert "Aqui é da" not in sem
