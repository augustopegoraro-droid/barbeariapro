"""Contagem física de estoque — Fase 6 do módulo de Produtos/Estoque/Vendas.

Cobre abrir contagem (congela `expected_qty`), informar `counted_qty` por
item, finalizar (gera `stock_movements` tipo `inventario` só para itens
divergentes, saldo passa a refletir a contagem), RBAC (reception opera,
barbeiro não vê) e bloqueios de estado (patch/finalizar após finalizado).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, delete, select, text

from app.db.session import AsyncSessionLocal, set_current_org
from tests.conftest import SEED_ORG_ID
from models import InventoryCount, Product, ProductCategory, ProductVariant

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)

        product_ids = (
            (
                await session.execute(
                    select(Product.id).where(Product.name.like("Produto Inventario Teste%"))
                )
            )
            .scalars()
            .all()
        )
        variant_ids = (
            (
                await session.execute(
                    select(ProductVariant.id).where(ProductVariant.product_id.in_(product_ids))
                )
            )
            .scalars()
            .all()
            if product_ids
            else []
        )

        cleared = not variant_ids
        if variant_ids and ADMIN_URL:
            eng = create_engine(ADMIN_URL)
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM inventory_count_items WHERE variant_id = ANY(:ids)"
                    ),
                    {"ids": variant_ids},
                )
                conn.execute(text("DELETE FROM stock_movements WHERE variant_id = ANY(:ids)"), {"ids": variant_ids})
                conn.execute(
                    text(
                        "DELETE FROM inventory_counts WHERE id NOT IN (SELECT DISTINCT inventory_count_id FROM inventory_count_items)"
                    )
                )
            eng.dispose()
            cleared = True

        if product_ids and cleared:
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.execute(
            delete(ProductCategory).where(ProductCategory.name.like("Categoria Inventario Teste%"))
        )
        await session.commit()


def _suf() -> str:
    return str(uuid.uuid4().int % 1_000_000)


async def _criar_produto_com_saldo(client, auth_headers, qty: str = "10") -> int:
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Produto Inventario Teste {_suf()}",
            "tracks_stock": True,
            "variants": [{"name": "Único", "price": "5.00"}],
        },
    )
    assert resp.status_code == 201, resp.text
    variant_id = resp.json()["variants"][0]["id"]

    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": qty},
    )
    assert resp.status_code == 201, resp.text
    return variant_id


@pytest.mark.asyncio
async def test_abrir_inventario_congela_expected_qty(client, auth_headers):
    variant_id = await _criar_produto_com_saldo(client, auth_headers, qty="10")

    resp = await client.post("/estoque/inventarios", headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "aberto"
    item = next(i for i in body["items"] if i["variant_id"] == variant_id)
    assert item["expected_qty"] == 10.0
    assert item["counted_qty"] is None


@pytest.mark.asyncio
async def test_finalizar_sem_divergencia_nao_gera_movimentacao(client, auth_headers):
    variant_id = await _criar_produto_com_saldo(client, auth_headers, qty="10")

    resp = await client.post("/estoque/inventarios", headers=auth_headers)
    count_id = resp.json()["id"]
    item_id = next(i["id"] for i in resp.json()["items"] if i["variant_id"] == variant_id)

    resp = await client.patch(
        f"/estoque/inventarios/{count_id}/itens/{item_id}",
        headers=auth_headers,
        json={"counted_qty": "10"},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(f"/estoque/inventarios/{count_id}/finalizar", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "finalizado"

    resp = await client.get("/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id})
    assert all(m["movement_type"] != "inventario" for m in resp.json())


@pytest.mark.asyncio
async def test_finalizar_com_divergencia_gera_movimentacao_inventario(client, auth_headers):
    variant_id = await _criar_produto_com_saldo(client, auth_headers, qty="10")

    resp = await client.post("/estoque/inventarios", headers=auth_headers)
    count_id = resp.json()["id"]
    item_id = next(i["id"] for i in resp.json()["items"] if i["variant_id"] == variant_id)

    resp = await client.patch(
        f"/estoque/inventarios/{count_id}/itens/{item_id}",
        headers=auth_headers,
        json={"counted_qty": "7"},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(f"/estoque/inventarios/{count_id}/finalizar", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    resp = await client.get("/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id})
    movs = resp.json()
    inv_mov = next(m for m in movs if m["movement_type"] == "inventario")
    assert inv_mov["qty_delta"] == -3.0
    assert inv_mov["qty_after"] == 7.0


@pytest.mark.asyncio
async def test_finalizar_ignora_item_sem_contagem_informada(client, auth_headers):
    variant_a = await _criar_produto_com_saldo(client, auth_headers, qty="5")
    variant_b = await _criar_produto_com_saldo(client, auth_headers, qty="8")

    resp = await client.post("/estoque/inventarios", headers=auth_headers)
    count_id = resp.json()["id"]
    item_a = next(i["id"] for i in resp.json()["items"] if i["variant_id"] == variant_a)

    resp = await client.patch(
        f"/estoque/inventarios/{count_id}/itens/{item_a}",
        headers=auth_headers,
        json={"counted_qty": "5"},
    )
    assert resp.status_code == 200

    resp = await client.post(f"/estoque/inventarios/{count_id}/finalizar", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    resp = await client.get("/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_b})
    assert all(m["movement_type"] != "inventario" for m in resp.json())


@pytest.mark.asyncio
async def test_patch_apos_finalizar_409(client, auth_headers):
    variant_id = await _criar_produto_com_saldo(client, auth_headers, qty="10")

    resp = await client.post("/estoque/inventarios", headers=auth_headers)
    count_id = resp.json()["id"]
    item_id = next(i["id"] for i in resp.json()["items"] if i["variant_id"] == variant_id)

    await client.post(f"/estoque/inventarios/{count_id}/finalizar", headers=auth_headers)

    resp = await client.patch(
        f"/estoque/inventarios/{count_id}/itens/{item_id}",
        headers=auth_headers,
        json={"counted_qty": "1"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_finalizar_duas_vezes_409(client, auth_headers):
    await _criar_produto_com_saldo(client, auth_headers, qty="10")

    resp = await client.post("/estoque/inventarios", headers=auth_headers)
    count_id = resp.json()["id"]

    resp = await client.post(f"/estoque/inventarios/{count_id}/finalizar", headers=auth_headers)
    assert resp.status_code == 200

    resp = await client.post(f"/estoque/inventarios/{count_id}/finalizar", headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reception_pode_gerenciar_inventario(client, auth_headers, reception_headers):
    await _criar_produto_com_saldo(client, auth_headers, qty="10")

    resp = await client.post("/estoque/inventarios", headers=reception_headers)
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_barber_nao_pode_abrir_inventario_403(client, barber_headers):
    resp = await client.post("/estoque/inventarios", headers=barber_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_rls_isola_inventario_entre_orgs(client, auth_headers):
    await _criar_produto_com_saldo(client, auth_headers, qty="10")
    resp = await client.post("/estoque/inventarios", headers=auth_headers)
    count_id = resp.json()["id"]

    other_org_id = SEED_ORG_ID + 999_000
    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org_id)
        rows = (
            await session.execute(select(InventoryCount).where(InventoryCount.id == count_id))
        ).scalars().all()
        assert rows == []
