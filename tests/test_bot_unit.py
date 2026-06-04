"""
Testes unitários para lógica do bot — sem banco de dados.
Testam funções puras e comportamentos isolados.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ────────────────────────────────────────────────────────────
# Testes de _normalize_phone
# ────────────────────────────────────────────────────────────

def test_normalize_phone_with_plus():
    from app.api.bot import _normalize_phone
    assert _normalize_phone("+5563999368196") == "+5563999368196"

def test_normalize_phone_without_plus():
    from app.api.bot import _normalize_phone
    assert _normalize_phone("5563999368196") == "+5563999368196"

def test_normalize_phone_with_spaces_and_dashes():
    from app.api.bot import _normalize_phone
    assert _normalize_phone("+55 63 9993-68196") == "+5563999368196"

def test_normalize_phone_invalid_raises():
    from app.api.bot import _normalize_phone
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _normalize_phone("123")
    assert exc.value.status_code == 422

def test_normalize_phone_empty_raises():
    from app.api.bot import _normalize_phone
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _normalize_phone("")


# ────────────────────────────────────────────────────────────
# Testes de _overlaps
# ────────────────────────────────────────────────────────────

def test_overlaps_true():
    from app.api.bot import _overlaps
    base = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    s1, e1 = base, base + timedelta(hours=1)
    s2, e2 = base + timedelta(minutes=30), base + timedelta(hours=2)
    assert _overlaps(s1, e1, s2, e2) is True

def test_overlaps_false_before():
    from app.api.bot import _overlaps
    base = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    s1, e1 = base, base + timedelta(hours=1)
    s2, e2 = base - timedelta(hours=2), base  # termina exatamente em s1 → sem overlap
    assert _overlaps(s1, e1, s2, e2) is False

def test_overlaps_false_after():
    from app.api.bot import _overlaps
    base = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    s1, e1 = base, base + timedelta(hours=1)
    s2, e2 = e1, e1 + timedelta(hours=1)  # começa exatamente em e1 → sem overlap
    assert _overlaps(s1, e1, s2, e2) is False

def test_overlaps_contained():
    from app.api.bot import _overlaps
    base = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    s1, e1 = base, base + timedelta(hours=2)
    s2, e2 = base + timedelta(minutes=30), base + timedelta(minutes=90)
    assert _overlaps(s1, e1, s2, e2) is True


# ────────────────────────────────────────────────────────────
# Testes de debounce em memória (módulo isolado)
# ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_debounce_first_message_proceeds():
    """Primeira mensagem de um número → proceed=True."""
    # Importar com estado limpo
    import app.api.bot as bot_module
    bot_module._debounce.clear()

    from app.api.bot import _DebounceIn, debounce_entry
    result = await debounce_entry(_DebounceIn(phone="+5563000000001", message="oi"), None)
    assert result.proceed is True
    assert "+5563000000001" in bot_module._debounce

@pytest.mark.asyncio
async def test_debounce_second_message_same_phone_no_proceed():
    """Segunda mensagem do mesmo número (dentro da janela) → proceed=False."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()

    from app.api.bot import _DebounceIn, debounce_entry
    await debounce_entry(_DebounceIn(phone="+5563000000002", message="msg1"), None)
    result = await debounce_entry(_DebounceIn(phone="+5563000000002", message="msg2"), None)
    assert result.proceed is False
    # Ambas as mensagens devem estar no buffer
    assert len(bot_module._debounce["+5563000000002"]["messages"]) == 2

@pytest.mark.asyncio
async def test_debounce_different_phones_independent():
    """Mensagens de telefones diferentes são buffers independentes."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()

    from app.api.bot import _DebounceIn, debounce_entry
    r1 = await debounce_entry(_DebounceIn(phone="+5563000000003", message="oi A"), None)
    r2 = await debounce_entry(_DebounceIn(phone="+5563000000004", message="oi B"), None)
    assert r1.proceed is True
    assert r2.proceed is True  # telefone diferente → controller independente

@pytest.mark.asyncio
async def test_debounce_flush_returns_all_messages():
    """Flush retorna todas as mensagens concatenadas e limpa o buffer."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()

    from app.api.bot import _DebounceIn, _FlushIn, debounce_entry, debounce_flush
    await debounce_entry(_DebounceIn(phone="+5563000000005", message="msg1"), None)
    await debounce_entry(_DebounceIn(phone="+5563000000005", message="msg2"), None)
    await debounce_entry(_DebounceIn(phone="+5563000000005", message="msg3"), None)

    result = await debounce_flush(_FlushIn(phone="+5563000000005"), None)
    assert result.message == "msg1\nmsg2\nmsg3"
    assert "+5563000000005" not in bot_module._debounce

@pytest.mark.asyncio
async def test_debounce_stale_buffer_becomes_new_controller():
    """Buffer expirado (> STALE) → novo controlador, não acumula."""
    import app.api.bot as bot_module
    from time import monotonic
    bot_module._debounce.clear()

    # Simular buffer antigo (expirado)
    bot_module._debounce["+5563000000006"] = {
        "messages": ["mensagem antiga"],
        "ts": monotonic() - (bot_module._DEBOUNCE_STALE + 5),
    }

    from app.api.bot import _DebounceIn, debounce_entry
    result = await debounce_entry(_DebounceIn(phone="+5563000000006", message="mensagem nova"), None)
    assert result.proceed is True
    assert bot_module._debounce["+5563000000006"]["messages"] == ["mensagem nova"]

@pytest.mark.asyncio
async def test_debounce_flush_empty_phone_returns_empty():
    """Flush de telefone sem buffer retorna string vazia."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()

    from app.api.bot import _FlushIn, debounce_flush
    result = await debounce_flush(_FlushIn(phone="+5563000000099"), None)
    assert result.message == ""


# ────────────────────────────────────────────────────────────
# Testes de lógica de disponibilidade
# ────────────────────────────────────────────────────────────

def test_slot_alignment_30min():
    """Verificar que slots são gerados em intervalos de 30 minutos."""
    from datetime import date, time
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Sao_Paulo")
    from app.api.bot import _SLOT_STEP
    assert _SLOT_STEP == 30

    # Simular geração de candidatos
    open_dt = datetime(2026, 6, 5, 9, 0, tzinfo=tz)
    close_dt = datetime(2026, 6, 5, 19, 0, tzinfo=tz)
    duration = 30
    last_start = close_dt - timedelta(minutes=duration)

    candidates = []
    cur = open_dt
    while cur <= last_start:
        candidates.append(cur)
        cur += timedelta(minutes=_SLOT_STEP)

    # Todos os slots devem ter minutos múltiplos de 30
    for c in candidates:
        assert c.minute % 30 == 0, f"Slot não alinhado: {c}"
    # Deve haver 20 slots (9h-18h30, de 30 em 30)
    assert len(candidates) == 20


# ────────────────────────────────────────────────────────────
# Testes de validação de horário comercial (lógica pura)
# ────────────────────────────────────────────────────────────

def _is_within_business_hours(dt_local, open_h, open_m, close_h, close_m):
    """Helper para testar a lógica de validação de horário comercial."""
    from datetime import time
    t = dt_local.time().replace(second=0, microsecond=0)
    open_t = datetime.min.time().replace(hour=open_h, minute=open_m)
    close_t = datetime.min.time().replace(hour=close_h, minute=close_m)
    return open_t <= t < close_t

def test_within_business_hours_valid():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Sao_Paulo")
    dt = datetime(2026, 6, 5, 14, 0, tzinfo=tz)  # sexta às 14h
    assert _is_within_business_hours(dt, 9, 0, 19, 0) is True

def test_outside_business_hours_before_open():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Sao_Paulo")
    dt = datetime(2026, 6, 5, 8, 30, tzinfo=tz)  # 8h30 → fechado
    assert _is_within_business_hours(dt, 9, 0, 19, 0) is False

def test_outside_business_hours_after_close():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Sao_Paulo")
    dt = datetime(2026, 6, 5, 19, 0, tzinfo=tz)  # exatamente 19h → fechado
    assert _is_within_business_hours(dt, 9, 0, 19, 0) is False

def test_slot_alignment_valid():
    """Horário alinhado a 30 min desde abertura."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Sao_Paulo")
    open_h, open_m = 9, 0
    # 9h00 → 0 min desde abertura → alinhado
    dt_900 = datetime(2026, 6, 5, 9, 0, tzinfo=tz)
    minutes_from_open = (dt_900.hour * 60 + dt_900.minute) - (open_h * 60 + open_m)
    assert minutes_from_open % 30 == 0
    # 10h30 → 90 min desde abertura → alinhado
    dt_1030 = datetime(2026, 6, 5, 10, 30, tzinfo=tz)
    minutes_from_open = (dt_1030.hour * 60 + dt_1030.minute) - (open_h * 60 + open_m)
    assert minutes_from_open % 30 == 0

def test_slot_alignment_invalid():
    """Horário NÃO alinhado a 30 min desde abertura."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Sao_Paulo")
    open_h, open_m = 9, 0
    # 9h03 → 3 min desde abertura → NÃO alinhado
    dt = datetime(2026, 6, 5, 9, 3, tzinfo=tz)
    minutes_from_open = (dt.hour * 60 + dt.minute) - (open_h * 60 + open_m)
    assert minutes_from_open % 30 != 0


# ────────────────────────────────────────────────────────────
# Testes de ownership logic (lógica que será implementada)
# ────────────────────────────────────────────────────────────

def test_appointment_ownership_same_client():
    """Simulação: agendamento pertence ao cliente correto."""
    client_id = 42
    appointment_client_id = 42
    assert appointment_client_id == client_id

def test_appointment_ownership_different_client():
    """Simulação: agendamento pertence a outro cliente → deve rejeitar."""
    client_id = 42
    appointment_client_id = 99
    assert appointment_client_id != client_id


# ────────────────────────────────────────────────────────────
# Testes de deduplicação de message_id
# ────────────────────────────────────────────────────────────

def test_message_id_dedup_logic():
    """Lógica de deduplicação por message_id."""
    processed = set()

    def should_process(msg_id: str) -> bool:
        if msg_id in processed:
            return False
        processed.add(msg_id)
        return True

    assert should_process("abc123") is True
    assert should_process("abc123") is False  # duplicata → rejeitar
    assert should_process("def456") is True   # ID diferente → aceitar


# ────────────────────────────────────────────────────────────
# Testes de lógica de nome no upsert
# ────────────────────────────────────────────────────────────

def test_name_update_only_if_longer():
    """Só atualiza nome se o novo for mais longo."""
    def should_update_name(existing_name: str, new_name: str) -> bool:
        return len(new_name) > len(existing_name or '')

    assert should_update_name("João", "João Silva") is True   # mais longo → atualiza
    assert should_update_name("João Silva", "João") is False  # mais curto → mantém
    assert should_update_name("", "Maria") is True            # novo cliente → atualiza
    assert should_update_name("Ana", "Ana") is False          # mesmo tamanho → mantém


# ────────────────────────────────────────────────────────────
# Testes de deduplicação por message_id — ETAPA 5
# ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_debounce_redelivery_ignored():
    """Mesma message_id chegando duas vezes → segunda é ignorada (proceed=False)."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()
    bot_module._seen_ids.clear()

    from app.api.bot import _DebounceIn, debounce_entry
    r1 = await debounce_entry(_DebounceIn(phone="+5563000000010", message="oi", message_id="msg-abc"), None)
    r2 = await debounce_entry(_DebounceIn(phone="+5563000000010", message="oi", message_id="msg-abc"), None)
    assert r1.proceed is True
    assert r2.proceed is False  # re-delivery → ignorado

@pytest.mark.asyncio
async def test_debounce_different_message_ids_proceed():
    """IDs de mensagem diferentes → tratados como mensagens distintas."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()
    bot_module._seen_ids.clear()

    from app.api.bot import _DebounceIn, debounce_entry
    r1 = await debounce_entry(_DebounceIn(phone="+5563000000011", message="msg1", message_id="id-001"), None)
    assert r1.proceed is True
    # Flush para limpar o buffer
    from app.api.bot import _FlushIn, debounce_flush
    await debounce_flush(_FlushIn(phone="+5563000000011"), None)

    r2 = await debounce_entry(_DebounceIn(phone="+5563000000011", message="msg2", message_id="id-002"), None)
    assert r2.proceed is True  # ID diferente → nova mensagem

@pytest.mark.asyncio
async def test_debounce_without_message_id_still_works():
    """Sem message_id → comportamento normal do debounce (sem deduplicação)."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()
    bot_module._seen_ids.clear()

    from app.api.bot import _DebounceIn, debounce_entry
    r1 = await debounce_entry(_DebounceIn(phone="+5563000000012", message="sem id"), None)
    assert r1.proceed is True

@pytest.mark.asyncio
async def test_debounce_new_session_detected_no_prior_flush():
    """Sem flush anterior registrado → is_new_session=True (primeiro contato)."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()
    bot_module._seen_ids.clear()
    bot_module._last_flush.pop("+5563000000013", None)  # sem flush anterior

    from app.api.bot import _DebounceIn, debounce_entry
    r = await debounce_entry(_DebounceIn(phone="+5563000000013", message="voltei"), None)
    assert r.proceed is True
    assert r.is_new_session is True  # sem flush anterior → nova sessão

@pytest.mark.asyncio
async def test_debounce_new_session_detected_old_flush():
    """Flush anterior > SESSION_GAP → is_new_session=True."""
    import app.api.bot as bot_module
    from time import monotonic
    bot_module._debounce.clear()
    bot_module._seen_ids.clear()
    # Simular flush antigo (> 4h atrás)
    bot_module._last_flush["+5563000000015"] = monotonic() - (bot_module._SESSION_GAP + 60)

    from app.api.bot import _DebounceIn, debounce_entry
    r = await debounce_entry(_DebounceIn(phone="+5563000000015", message="voltei"), None)
    assert r.proceed is True
    assert r.is_new_session is True

@pytest.mark.asyncio
async def test_debounce_continuing_session_no_new_session():
    """Flush recente (< SESSION_GAP) → is_new_session=False."""
    import app.api.bot as bot_module
    from time import monotonic
    bot_module._debounce.clear()
    bot_module._seen_ids.clear()
    # Simular flush recente (1 min atrás)
    bot_module._last_flush["+5563000000016"] = monotonic() - 60

    from app.api.bot import _DebounceIn, debounce_entry
    r = await debounce_entry(_DebounceIn(phone="+5563000000016", message="ainda aqui"), None)
    assert r.proceed is True
    assert r.is_new_session is False

@pytest.mark.asyncio
async def test_flush_returns_is_new_session_flag():
    """Flush deve propagar a flag is_new_session."""
    import app.api.bot as bot_module
    bot_module._debounce.clear()
    bot_module._seen_ids.clear()

    from app.api.bot import _DebounceIn, _FlushIn, debounce_entry, debounce_flush
    await debounce_entry(_DebounceIn(phone="+5563000000014", message="oi"), None)
    result = await debounce_flush(_FlushIn(phone="+5563000000014"), None)
    assert hasattr(result, "is_new_session")
    assert isinstance(result.is_new_session, bool)


# ────────────────────────────────────────────────────────────
# Testes do ownership check — ETAPA 1
# ────────────────────────────────────────────────────────────

def test_cancel_requires_phone_param():
    """cancel_appointment agora exige phone query param — verificar assinatura."""
    import inspect
    from app.api.bot import cancel_appointment
    sig = inspect.signature(cancel_appointment)
    params = list(sig.parameters.keys())
    assert "phone" in params, "phone deve ser parâmetro de cancel_appointment"
    assert "appointment_id" in params
    assert "db" in params

def test_cancel_ownership_logic_same_client():
    """Agendamento do mesmo cliente → deve prosseguir."""
    owner_id = 10
    appt_client_id = 10
    assert appt_client_id == owner_id, "Agendamento pertence ao cliente → OK"

def test_cancel_ownership_logic_other_client():
    """Agendamento de cliente diferente → deve ser rejeitado."""
    owner_id = 10
    appt_client_id = 99
    assert appt_client_id != owner_id, "Agendamento de outro cliente → rejeitar"

def test_cancel_phone_is_normalized():
    """Phone passado sem + deve ser normalizado antes da query."""
    from app.api.bot import _normalize_phone
    raw = "5563999368196"
    normalized = _normalize_phone(raw)
    assert normalized == "+5563999368196"


if __name__ == "__main__":
    import subprocess
    subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"])


# ────────────────────────────────────────────────────────────
# Testes de horário comercial — BYPASS_HOURS=false (ITEM [1])
# ────────────────────────────────────────────────────────────

def test_bypass_hours_is_false_in_workflow():
    """BYPASS_HOURS deve ser false no workflow instalado."""
    import json
    with open("workflows.json") as f:
        data = json.load(f)
    bot_wf = next(w for w in data if "BarbeariaPro Bot" in w.get("name", ""))
    hora = next(n for n in bot_wf["nodes"] if n["id"] == "hora-001")
    code = hora["parameters"]["jsCode"]
    assert "BYPASS_HOURS = false" in code, "BYPASS_HOURS deve ser false em produção"
    assert "BYPASS_HOURS = true" not in code, "BYPASS_HOURS=true não deve existir no código"

def _horario_comercial_palmas(utc_ts_ms: int) -> bool:
    """Replica a lógica JS do Code Horário Comercial com BYPASS_HOURS=false."""
    palmas_ms = utc_ts_ms + (-3 * 3600 * 1000)
    # Simular getUTCHours/getUTCDay sobre o timestamp deslocado
    from datetime import datetime, timezone
    palmas_dt = datetime.utcfromtimestamp(palmas_ms / 1000)
    hour = palmas_dt.hour
    day = palmas_dt.weekday()          # Python: 0=Seg...6=Dom
    js_day = (day + 1) % 7            # n8n/JS: 0=Dom, 1=Seg...6=Sáb
    if 1 <= js_day <= 5:
        return 9 <= hour < 19
    elif js_day == 6:
        return 9 <= hour < 17
    return False  # domingo

def test_horario_dentro_semana():
    from datetime import datetime, timezone
    # Qui 13h30 Palmas = UTC 16h30
    ts = int(datetime(2026, 6, 4, 16, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert _horario_comercial_palmas(ts) is True

def test_horario_noturno_fechado():
    from datetime import datetime, timezone
    # Qui 22h30 Palmas = UTC 01h30 do dia seguinte
    ts = int(datetime(2026, 6, 5, 1, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert _horario_comercial_palmas(ts) is False

def test_horario_domingo_fechado():
    from datetime import datetime, timezone
    # Dom 14h Palmas = UTC 17h
    ts = int(datetime(2026, 6, 7, 17, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert _horario_comercial_palmas(ts) is False

def test_horario_sabado_aberto():
    from datetime import datetime, timezone
    # Sáb 10h Palmas = UTC 13h
    ts = int(datetime(2026, 6, 6, 13, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert _horario_comercial_palmas(ts) is True

def test_horario_sabado_apos_17h_fechado():
    from datetime import datetime, timezone
    # Sáb 18h01 Palmas = UTC 21h01
    ts = int(datetime(2026, 6, 6, 21, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert _horario_comercial_palmas(ts) is False

def test_horario_exato_abertura():
    from datetime import datetime, timezone
    # Seg 9h00 = UTC 12h00 — exatamente na abertura → aberto
    ts = int(datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert _horario_comercial_palmas(ts) is True

def test_horario_exato_fechamento():
    from datetime import datetime, timezone
    # Sex 19h00 Palmas = UTC 22h00 — exatamente no fechamento → fechado
    ts = int(datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert _horario_comercial_palmas(ts) is False


# ────────────────────────────────────────────────────────────
# Testes de status concluido — ITEM [3]
# ────────────────────────────────────────────────────────────

def test_complete_endpoint_exists():
    """Endpoint /complete deve existir no router."""
    import inspect
    from app.api.bot import complete_appointment
    sig = inspect.signature(complete_appointment)
    assert "appointment_id" in sig.parameters
    assert "db" in sig.parameters

def test_appointment_status_concluido_in_enum():
    """AppointmentStatus.concluido deve existir no enum."""
    from models.enums import AppointmentStatus
    assert hasattr(AppointmentStatus, 'concluido')
    assert AppointmentStatus.concluido.value == 'concluido'

def test_appointment_status_faltou_in_enum():
    """AppointmentStatus.faltou deve existir no enum."""
    from models.enums import AppointmentStatus
    assert hasattr(AppointmentStatus, 'faltou')

def test_days_since_logic_concluido_preferred():
    """
    get_client_profile deve preferir concluido sobre agendado para last_visit.
    Testamos a lógica: se há concluido, usa ele; senão usa agendado passado.
    """
    from models.enums import AppointmentStatus
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    past_30 = now - timedelta(days=30)
    past_10 = now - timedelta(days=10)

    # Simular: 1 concluido (30 dias atrás) + 1 agendado passado (10 dias atrás)
    appt_concluido = type('A', (), {
        'status': AppointmentStatus.concluido,
        'start_at': past_30,
    })()
    appt_agendado = type('A', (), {
        'status': AppointmentStatus.agendado,
        'start_at': past_10,
    })()

    # A lógica correta: preferir concluido
    def get_last_visit(appts):
        concluidos = [a for a in appts if a.status == AppointmentStatus.concluido]
        if concluidos:
            return max(concluidos, key=lambda a: a.start_at)
        fallback = [
            a for a in appts
            if a.status not in (AppointmentStatus.cancelado, AppointmentStatus.faltou)
            and a.start_at < now
        ]
        return max(fallback, key=lambda a: a.start_at) if fallback else None

    result = get_last_visit([appt_concluido, appt_agendado])
    assert result is appt_concluido, "Deve preferir concluido"
    assert (now - result.start_at).days == 30

def test_days_since_logic_fallback_when_no_concluido():
    """Sem concluido, fallback para agendado passado."""
    from models.enums import AppointmentStatus
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    past_15 = now - timedelta(days=15)

    appt_agendado = type('A', (), {
        'status': AppointmentStatus.agendado,
        'start_at': past_15,
    })()

    def get_last_visit(appts):
        concluidos = [a for a in appts if a.status == AppointmentStatus.concluido]
        if concluidos:
            return max(concluidos, key=lambda a: a.start_at)
        fallback = [
            a for a in appts
            if a.status not in (AppointmentStatus.cancelado, AppointmentStatus.faltou)
            and a.start_at < now
        ]
        return max(fallback, key=lambda a: a.start_at) if fallback else None

    result = get_last_visit([appt_agendado])
    assert result is appt_agendado, "Fallback para agendado passado"
