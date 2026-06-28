"""Testes de integração (via API) da fidelidade por pontos — Fase 2.

Pulam automaticamente se o DB semeado não estiver disponível (fixture auth_headers).
"""

from __future__ import annotations

import time

import pytest


async def _make_client(client, auth_headers) -> int:
    phone = f"+5511{time.time_ns() % 100_000_000:08d}"
    resp = await client.post(
        "/clientes", json={"name": "Cliente Pontos", "phone": phone}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_tiers_e_rules_default(client, auth_headers):
    r = await client.get("/loyalty/tiers", headers=auth_headers)
    assert r.status_code == 200, r.text
    names = [t["name"] for t in r.json()]
    assert names == ["Bronze", "Prata", "Ouro", "Diamante", "Black"]

    r = await client.get("/loyalty/rules", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["points_per_brl"] == 1.0
    assert r.json()["points_per_visit"] == 10


@pytest.mark.asyncio
async def test_ajuste_resgate_e_extrato(client, auth_headers):
    cid = await _make_client(client, auth_headers)
    try:
        # Ajuste +600 → tier Ouro (>=500)
        r = await client.post(
            f"/loyalty/clients/{cid}/points",
            json={"delta": 600, "reason": "teste"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["points_balance"] == 600
        assert r.json()["tier_name"] == "Ouro"

        # Extrato tem o lançamento
        r = await client.get(f"/loyalty/clients/{cid}/ledger", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()[0]["balance_after"] == 600
        assert r.json()[0]["type"] == "adjust"

        # Resgate de 100 pontos → voucher de R$100, saldo cai p/ 500
        r = await client.post(
            f"/loyalty/clients/{cid}/redeem", json={"points": 100}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["amount_brl"] == 100.0
        assert r.json()["points_spent"] == 100
        assert r.json()["status"] == "ativo"

        r = await client.get(f"/loyalty/clients/{cid}/ledger", headers=auth_headers)
        assert r.json()[0]["balance_after"] == 500
        assert r.json()[0]["type"] == "redeem"

        # Voucher listado
        r = await client.get(f"/loyalty/clients/{cid}/vouchers", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1
    finally:
        await client.delete(f"/clientes/{cid}", headers=auth_headers)


@pytest.mark.asyncio
async def test_resgate_acima_do_saldo_falha_409(client, auth_headers):
    cid = await _make_client(client, auth_headers)
    try:
        await client.post(
            f"/loyalty/clients/{cid}/points", json={"delta": 50, "reason": "t"}, headers=auth_headers
        )
        r = await client.post(
            f"/loyalty/clients/{cid}/redeem", json={"points": 99999}, headers=auth_headers
        )
        assert r.status_code == 409, r.text
        # saldo intacto
        r = await client.get(f"/loyalty/clients/{cid}/ledger", headers=auth_headers)
        assert r.json()[0]["balance_after"] == 50
    finally:
        await client.delete(f"/clientes/{cid}", headers=auth_headers)


@pytest.mark.asyncio
async def test_loyalty_config_exige_autenticacao(client):
    r = await client.get("/loyalty/tiers")
    assert r.status_code in (401, 403)
