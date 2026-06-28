"""Testes unitários (sem DB) da fidelidade por pontos — Fase 2."""

from __future__ import annotations

from decimal import Decimal

from app.services import loyalty as L
from models.enums import LoyaltyCategoria, LoyaltyNivel
from models.loyalty import LoyaltyRule, LoyaltyTier
from scripts.backfill_loyalty_points import _floor_min_points


def _tiers() -> list[LoyaltyTier]:
    return [
        LoyaltyTier(name="Bronze", min_points=0),
        LoyaltyTier(name="Prata", min_points=150),
        LoyaltyTier(name="Ouro", min_points=500),
        LoyaltyTier(name="Diamante", min_points=1000),
        LoyaltyTier(name="Black", min_points=2000),
    ]


def test_tier_for_points():
    t = _tiers()
    assert L.tier_for_points(0, t).name == "Bronze"
    assert L.tier_for_points(149, t).name == "Bronze"
    assert L.tier_for_points(150, t).name == "Prata"
    assert L.tier_for_points(360, t).name == "Prata"
    assert L.tier_for_points(2500, t).name == "Black"


def test_tier_for_points_independe_da_ordem():
    desordenado = list(reversed(_tiers()))
    assert L.tier_for_points(500, desordenado).name == "Ouro"


def test_points_to_next_tier():
    t = _tiers()
    assert L.points_to_next_tier(360, t) == {"next_tier": "Ouro", "points_needed": 140}
    assert L.points_to_next_tier(2500, t) == {"next_tier": None, "points_needed": 0}


def test_points_for_appointment():
    rule = LoyaltyRule(points_per_brl=Decimal("1"), points_per_visit=10)
    assert L.points_for_appointment(Decimal("45"), rule) == 55  # 45 + 10
    assert L.points_for_appointment(Decimal("0"), rule) == 10
    assert L.points_for_appointment(None, rule) == 10


def test_points_for_appointment_arredonda_half_up():
    rule = LoyaltyRule(points_per_brl=Decimal("0.5"), points_per_visit=0)
    assert L.points_for_appointment(Decimal("45"), rule) == 23  # 22.5 → 23 (HALF_UP)


def test_floor_min_points_pega_o_maior_eixo():
    t = _tiers()
    # vip (Diamante=1000) vs bronze (Bronze=0) → 1000
    assert _floor_min_points(LoyaltyNivel.vip, LoyaltyCategoria.bronze, t) == 1000
    # ativo (Prata=150) vs ouro (Ouro=500) → 500
    assert _floor_min_points(LoyaltyNivel.ativo, LoyaltyCategoria.ouro, t) == 500
    # sem categoria
    assert _floor_min_points(LoyaltyNivel.fiel, None, t) == 500
    # novo + None → 0
    assert _floor_min_points(LoyaltyNivel.novo, None, t) == 0
