"""Testes do parser de agendamentos da Trinks (puro, sem DB)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.services.trinks_appointments import parse_appointments

FIXTURE = Path(__file__).parent / "fixtures" / "trinks" / "agendamentos_sample.csv"


def test_report_counts():
    recs, rep = parse_appointments(FIXTURE)
    assert rep.total_rows == 5
    assert rep.parsed == 4          # 1 cancelado excluído
    assert rep.cancelled_skipped == 1
    assert rep.unmapped_service == 1
    assert rep.no_phone == 1
    assert rep.bad_datetime == 0
    assert len(recs) == 4


def test_first_record_mapping_and_tz():
    recs, _ = parse_appointments(FIXTURE)
    r = recs[0]
    assert r.barber_name == "THEDY"
    assert r.service_system == "Corte Masculino"   # de-para
    assert r.duration_min == 30
    assert r.price == Decimal("90.00")
    assert r.client_phone == "+5563992271490"
    # 09:00 em America/Sao_Paulo (UTC-3) → 12:00 UTC
    assert r.start_utc == datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def test_composite_duration_and_email():
    recs, _ = parse_appointments(FIXTURE)
    r = recs[1]
    assert r.duration_min == 90                     # "1h e 30 min"
    assert r.service_system == "Mechas"
    assert r.price == Decimal("600.00")
    assert r.client_email == "dois@x.com"
    assert r.client_phone == "+5563999992327"


def test_unmapped_service_and_no_phone():
    recs, _ = parse_appointments(FIXTURE)
    unmapped = recs[2]   # SANDRA, serviço inexistente
    assert unmapped.service_system is None
    assert unmapped.service_trinks == "Servico Inexistente XYZ"
    no_phone = recs[3]   # THEDY, sem telefone
    assert no_phone.client_phone is None
