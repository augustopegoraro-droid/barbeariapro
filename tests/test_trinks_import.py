"""Testes do parser de import da Trinks (puro, sem DB).

Valida o mapeamento de colunas, normalização de telefone, dedup no arquivo,
parsing de data/e-mail/canal e o encoding latin-1 (fixture anonimizada).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services.trinks_import import parse_clients
from models.enums import ContactChannel

FIXTURE = Path(__file__).parent / "fixtures" / "trinks" / "clientes_sample.csv"


def test_parse_report_counts():
    records, report = parse_clients(FIXTURE)
    assert report.total_rows == 7
    assert report.importable == 3      # João, Maria, Carla
    assert report.no_name == 1         # linha 666
    assert report.no_phone == 1        # Ana
    assert report.invalid_phone == 1   # Pedro ("123")
    assert report.dup_in_file == 1     # 2º João (mesmo telefone)
    assert report.with_email == 2      # João, Carla (importáveis com e-mail)
    assert report.with_birth == 3      # João, Maria, Carla
    assert len(records) == 3


def test_first_record_full_mapping():
    records, _ = parse_clients(FIXTURE)
    joao = records[0]
    assert joao.name == "João Silva"
    assert joao.phone_e164 == "+5563992287396"
    assert joao.email == "joao@email.com"
    assert joao.birth_date == date(1990, 3, 15)
    assert joao.acquisition_channel == ContactChannel.instagram
    assert joao.notes == "Cliente fiel | Instagram: @joaosilva"


def test_phone2_fallback_and_channel():
    records, _ = parse_clients(FIXTURE)
    maria = records[1]
    assert maria.phone_e164 == "+5563991112222"   # veio de "Telefone 2"
    assert maria.email is None
    assert maria.birth_date == date(1985, 12, 20)
    assert maria.acquisition_channel == ContactChannel.passante  # "Balcão"
    assert maria.notes is None


def test_email_lowercased_and_accents_latin1():
    records, _ = parse_clients(FIXTURE)
    carla = records[2]
    assert carla.name == "Carla Açaí"             # encoding latin-1 ok
    assert carla.email == "carla@email.com"       # normalizado p/ minúsculas
    assert carla.acquisition_channel == ContactChannel.indicacao
    assert carla.notes == "Alérgica a amônia | Instagram: @carla_a"
