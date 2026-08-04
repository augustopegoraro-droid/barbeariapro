"""Fornecedores e pedidos de compra — Fase 5 do módulo de Produtos/Estoque/
Vendas.

Cobre criação de fornecedor, ciclo de vida do pedido (rascunho → enviado →
recebido, parcial ou total), recálculo de `cost_avg` por média ponderada no
recebimento, bloqueios de negócio (receber mais que o pedido, cancelar após
recebimento) e RBAC (recepção vê mas não gerencia; barbeiro sem acesso).
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, delete, select, text

from app.db.session import AsyncSessionLocal, set_current_org
from tests.conftest import SEED_ORG_ID
from models import Product, ProductCategory, ProductVariant

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")


def _suf() -> str:
    return str(uuid.uuid4().int % 1_000_000)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)

        product_ids = (
            (
                await session.execute(
                    select(Product.id).where(Product.name.like("Produto Compra Teste%"))
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
        if ADMIN_URL:
            eng = create_engine(ADMIN_URL)
            with eng.begin() as conn:
                supplier_ids = [
                    row[0]
                    for row in conn.execute(
                        text("SELECT id FROM suppliers WHERE name LIKE 'Fornecedor Teste%'")
                    )
                ]
                if supplier_ids:
                    po_ids = [
                        row[0]
                        for row in conn.execute(
                            text(
                                "SELECT id FROM purchase_orders WHERE supplier_id = ANY(:ids)"
                            ),
                            {"ids": supplier_ids},
                        )
                    ]
                    if po_ids:
                        conn.execute(
                            text(
                                "DELETE FROM purchase_order_items WHERE purchase_order_id = ANY(:ids)"
                            ),
                            {"ids": po_ids},
                        )
                        conn.execute(
                            text("DELETE FROM purchase_orders WHERE id = ANY(:ids)"),
                            {"ids": po_ids},
                        )
                    conn.execute(
                        text("DELETE FROM suppliers WHERE id = ANY(:ids)"),
                        {"ids": supplier_ids},
                    )
                if variant_ids:
                    conn.execute(
                        text("DELETE FROM stock_movements WHERE variant_id = ANY(:ids)"),
                        {"ids": variant_ids},
                    )
            eng.dispose()
            cleared = True

        if product_ids and cleared:
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.execute(
            delete(ProductCategory).where(ProductCategory.name.like("Categoria Compra Teste%"))
        )
        await session.commit()


async def _variant_snapshot(client, auth_headers, product_id: int) -> dict:
    resp = await client.get(f"/produtos/{product_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["variants"][0]


async def _criar_produto(client, auth_headers) -> tuple[int, int]:
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Produto Compra Teste {_suf()}",
            "tracks_stock": True,
            "variants": [{"name": "Único", "price": "10.00"}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["id"], body["variants"][0]["id"]


async def _criar_fornecedor(client, auth_headers) -> int:
    resp = await client.post(
        "/fornecedores",
        headers=auth_headers,
        json={"name": f"Fornecedor Teste {_suf()}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _criar_pedido(client, auth_headers, supplier_id, variant_id, qty="5", unit_cost="10.00") -> int:
    resp = await client.post(
        "/compras",
        headers=auth_headers,
        json={
            "supplier_id": supplier_id,
            "items": [{"variant_id": variant_id, "qty_ordered": qty, "unit_cost": unit_cost}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_criar_fornecedor(client, auth_headers):
    resp = await client.post(
        "/fornecedores", headers=auth_headers, json={"name": f"Fornecedor Teste {_suf()}"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["active"] is True


@pytest.mark.asyncio
async def test_pedido_nasce_rascunho(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)

    po = await _criar_pedido(client, auth_headers, supplier_id, variant_id)
    assert po["status"] == "rascunho"
    assert po["items"][0]["qty_received"] == 0.0


@pytest.mark.asyncio
async def test_enviar_pedido_muda_status(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)
    po = await _criar_pedido(client, auth_headers, supplier_id, variant_id)

    resp = await client.patch(f"/compras/{po['id']}/enviar", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "enviado"

    resp2 = await client.patch(f"/compras/{po['id']}/enviar", headers=auth_headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_receber_total_atualiza_estoque_e_cost_avg(client, auth_headers):
    product_id, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)
    po = await _criar_pedido(client, auth_headers, supplier_id, variant_id, qty="5", unit_cost="10.00")
    item_id = po["items"][0]["id"]
    await client.patch(f"/compras/{po['id']}/enviar", headers=auth_headers)

    resp = await client.post(
        f"/compras/{po['id']}/receber",
        headers=auth_headers,
        json={"items": [{"item_id": item_id, "qty": "5"}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "recebido"
    assert body["received_at"] is not None
    assert body["items"][0]["qty_received"] == 5.0

    variant = await _variant_snapshot(client, auth_headers, product_id)
    assert variant["stock_qty"] == 5.0
    assert variant["cost_avg"] == 10.0

    mov_resp = await client.get(
        "/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id}
    )
    entradas = [m for m in mov_resp.json() if m["movement_type"] == "entrada_compra"]
    assert len(entradas) == 1
    assert entradas[0]["reference_type"] == "purchase_order"
    assert entradas[0]["reference_id"] == po["id"]


@pytest.mark.asyncio
async def test_recebimento_recalcula_cost_avg_por_media_ponderada(client, auth_headers):
    product_id, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)

    po1 = await _criar_pedido(client, auth_headers, supplier_id, variant_id, qty="5", unit_cost="10.00")
    await client.patch(f"/compras/{po1['id']}/enviar", headers=auth_headers)
    await client.post(
        f"/compras/{po1['id']}/receber",
        headers=auth_headers,
        json={"items": [{"item_id": po1["items"][0]["id"], "qty": "5"}]},
    )

    po2 = await _criar_pedido(client, auth_headers, supplier_id, variant_id, qty="5", unit_cost="20.00")
    await client.patch(f"/compras/{po2['id']}/enviar", headers=auth_headers)
    await client.post(
        f"/compras/{po2['id']}/receber",
        headers=auth_headers,
        json={"items": [{"item_id": po2["items"][0]["id"], "qty": "5"}]},
    )

    variant = await _variant_snapshot(client, auth_headers, product_id)
    assert variant["stock_qty"] == 10.0
    # (5*10 + 5*20) / 10 = 15
    assert variant["cost_avg"] == 15.0


@pytest.mark.asyncio
async def test_recebimento_parcial_status_e_segundo_recebimento_completa(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)
    po = await _criar_pedido(client, auth_headers, supplier_id, variant_id, qty="10", unit_cost="10.00")
    item_id = po["items"][0]["id"]
    await client.patch(f"/compras/{po['id']}/enviar", headers=auth_headers)

    resp1 = await client.post(
        f"/compras/{po['id']}/receber",
        headers=auth_headers,
        json={"items": [{"item_id": item_id, "qty": "4"}]},
    )
    assert resp1.status_code == 200, resp1.text
    assert resp1.json()["status"] == "recebido_parcial"
    assert resp1.json()["items"][0]["qty_received"] == 4.0

    resp2 = await client.post(
        f"/compras/{po['id']}/receber",
        headers=auth_headers,
        json={"items": [{"item_id": item_id, "qty": "6"}]},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["status"] == "recebido"
    assert resp2.json()["items"][0]["qty_received"] == 10.0


@pytest.mark.asyncio
async def test_receber_mais_que_pedido_422(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)
    po = await _criar_pedido(client, auth_headers, supplier_id, variant_id, qty="3", unit_cost="10.00")
    item_id = po["items"][0]["id"]
    await client.patch(f"/compras/{po['id']}/enviar", headers=auth_headers)

    resp = await client.post(
        f"/compras/{po['id']}/receber",
        headers=auth_headers,
        json={"items": [{"item_id": item_id, "qty": "4"}]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_receber_pedido_em_rascunho_409(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)
    po = await _criar_pedido(client, auth_headers, supplier_id, variant_id)

    resp = await client.post(
        f"/compras/{po['id']}/receber",
        headers=auth_headers,
        json={"items": [{"item_id": po["items"][0]["id"], "qty": "1"}]},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancelar_pedido_rascunho_ok(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)
    po = await _criar_pedido(client, auth_headers, supplier_id, variant_id)

    resp = await client.patch(f"/compras/{po['id']}/cancelar", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelado"


@pytest.mark.asyncio
async def test_cancelar_pedido_apos_recebimento_409(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)
    po = await _criar_pedido(client, auth_headers, supplier_id, variant_id, qty="2", unit_cost="10.00")
    item_id = po["items"][0]["id"]
    await client.patch(f"/compras/{po['id']}/enviar", headers=auth_headers)
    await client.post(
        f"/compras/{po['id']}/receber",
        headers=auth_headers,
        json={"items": [{"item_id": item_id, "qty": "1"}]},
    )

    resp = await client.patch(f"/compras/{po['id']}/cancelar", headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_produto_sem_controle_estoque_bloqueia_compra_422(client, auth_headers):
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Produto Compra Teste {_suf()}",
            "tracks_stock": False,
            "variants": [{"name": "Único", "price": "3.00"}],
        },
    )
    assert resp.status_code == 201, resp.text
    variant_id = resp.json()["variants"][0]["id"]
    supplier_id = await _criar_fornecedor(client, auth_headers)

    po_resp = await client.post(
        "/compras",
        headers=auth_headers,
        json={
            "supplier_id": supplier_id,
            "items": [{"variant_id": variant_id, "qty_ordered": "1", "unit_cost": "1.00"}],
        },
    )
    assert po_resp.status_code == 422


@pytest.mark.asyncio
async def test_reception_ve_mas_nao_gerencia_fornecedores_e_compras(client, auth_headers, reception_headers):
    _, variant_id = await _criar_produto(client, auth_headers)
    supplier_id = await _criar_fornecedor(client, auth_headers)

    view_fornecedores = await client.get("/fornecedores", headers=reception_headers)
    assert view_fornecedores.status_code == 200

    manage_fornecedor = await client.post(
        "/fornecedores", headers=reception_headers, json={"name": f"Fornecedor Teste {_suf()}"}
    )
    assert manage_fornecedor.status_code == 403

    view_compras = await client.get("/compras", headers=reception_headers)
    assert view_compras.status_code == 200

    manage_compra = await client.post(
        "/compras",
        headers=reception_headers,
        json={
            "supplier_id": supplier_id,
            "items": [{"variant_id": variant_id, "qty_ordered": "1", "unit_cost": "10.00"}],
        },
    )
    assert manage_compra.status_code == 403


@pytest.mark.asyncio
async def test_barber_sem_acesso_a_fornecedores_403(client, barber_headers):
    resp = await client.get("/fornecedores", headers=barber_headers)
    assert resp.status_code == 403

    resp2 = await client.get("/compras", headers=barber_headers)
    assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_rls_isola_fornecedor_de_outra_org(client, auth_headers):
    supplier_id = await _criar_fornecedor(client, auth_headers)

    other_org_id = SEED_ORG_ID + 999_000
    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org_id)
        from models import Supplier

        result = await session.execute(select(Supplier).where(Supplier.id == supplier_id))
        assert result.scalar_one_or_none() is None
