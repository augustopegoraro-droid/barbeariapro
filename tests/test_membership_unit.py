"""Testes unitários das funções puras da mensalidade — sem banco.

Cobrem o cálculo do valor reconhecido por uso, o fim da vigência e, sobretudo,
o rateio do valor entre os serviços do combo (que vira `price_charged` e, por
consequência, receita e comissão). O invariante crítico é
`sum(rateio) == unit_value` exato — uma regressão aqui distorce o financeiro.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.membership import (
    _combo_matches,
    build_combo_snapshot,
    compute_end_at,
    compute_unit_value,
    rateio_price_charged,
    validate_combo_shape,
)


# ─── compute_unit_value ──────────────────────────────────────────────────────

def test_unit_value_finito_divide_preco_pelos_usos():
    assert compute_unit_value(Decimal("120"), 2, None) == Decimal("60.00")


def test_unit_value_finito_arredonda_duas_casas():
    assert compute_unit_value(Decimal("100"), 3, None) == Decimal("33.33")


def test_unit_value_ilimitado_usa_valor_configurado():
    assert compute_unit_value(Decimal("0"), None, Decimal("45")) == Decimal("45.00")


def test_unit_value_ilimitado_sem_valor_erra():
    with pytest.raises(ValueError):
        compute_unit_value(Decimal("0"), None, None)


# ─── compute_end_at ──────────────────────────────────────────────────────────

def test_end_at_soma_duracao_em_dias():
    start = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert compute_end_at(start, 30) == datetime(2026, 1, 31, 10, 0, tzinfo=timezone.utc)


# ─── build_combo_snapshot ────────────────────────────────────────────────────

def test_snapshot_ordena_por_posicao_e_serializa_preco():
    items = [
        SimpleNamespace(service_id=10, position=2),
        SimpleNamespace(service_id=20, position=1),
    ]
    services = {
        10: SimpleNamespace(price=Decimal("40")),
        20: SimpleNamespace(price=Decimal("25.5")),
    }
    snap = build_combo_snapshot(items, services)
    assert [c["service_id"] for c in snap] == [20, 10]  # ordenado por position
    assert snap[0]["base_price"] == "25.50"
    assert snap[1]["base_price"] == "40.00"


# ─── rateio_price_charged ────────────────────────────────────────────────────

def _combo(*pairs):
    # pairs = (service_id, base_price, position)
    return [
        {"service_id": sid, "base_price": str(bp), "position": pos}
        for sid, bp, pos in pairs
    ]


def test_rateio_proporcional_ao_preco_base():
    combo = _combo((1, "40.00", 1), (2, "20.00", 2))
    r = rateio_price_charged(Decimal("60.00"), combo)
    assert r[1] == Decimal("40.00")
    assert r[2] == Decimal("20.00")
    assert sum(r.values()) == Decimal("60.00")


def test_rateio_residuo_no_ultimo_item_soma_exata():
    combo = _combo((1, "1.00", 1), (2, "1.00", 2), (3, "1.00", 3))
    r = rateio_price_charged(Decimal("100.00"), combo)
    assert sum(r.values()) == Decimal("100.00")  # invariante
    assert r[3] == Decimal("33.34")  # resíduo no último


def test_rateio_combo_gratis_divide_igualmente():
    combo = _combo((1, "0.00", 1), (2, "0.00", 2))
    r = rateio_price_charged(Decimal("60.00"), combo)
    assert sum(r.values()) == Decimal("60.00")
    assert r[1] == Decimal("30.00")


def test_rateio_item_unico_recebe_tudo():
    combo = _combo((7, "99.99", 1))
    r = rateio_price_charged(Decimal("50.00"), combo)
    assert r[7] == Decimal("50.00")


# ─── validate_combo_shape (regra do catálogo: corte/barba/corte+barba) ───────

@pytest.mark.parametrize(
    "cats",
    [["cabelo"], ["barba"], ["combo"], ["cabelo", "barba"], ["barba", "cabelo"]],
)
def test_combo_shape_aceita_formas_validas(cats):
    validate_combo_shape(cats)  # não levanta


@pytest.mark.parametrize(
    "cats",
    [
        [],
        ["quimica"],
        ["estetica"],
        ["cabelo", "quimica"],
        ["cabelo", "cabelo"],
        ["barba", "barba"],
        ["cabelo", "combo"],
        ["cabelo", "barba", "barba"],
    ],
)
def test_combo_shape_rejeita_formas_invalidas(cats):
    with pytest.raises(ValueError):
        validate_combo_shape(cats)


# ─── _combo_matches ──────────────────────────────────────────────────────────

def test_combo_matches_igualdade_de_conjunto_ignora_ordem():
    combo = _combo((1, "10.00", 1), (2, "20.00", 2))
    assert _combo_matches(combo, [2, 1]) is True
    assert _combo_matches(combo, [1]) is False
    assert _combo_matches(combo, [1, 2, 3]) is False
    assert _combo_matches(combo, [1, 3]) is False
