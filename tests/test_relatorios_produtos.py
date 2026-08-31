"""Relatórios avançados de Produtos/Estoque/Vendas — Fase 7 (plano em
/Users/apleandro/.claude/plans/elabore-um-plano-completo-expressive-lovelace.md).

Cobre `GET /vendas/produtos-mais-vendidos` (top_selling_products) e
`GET /estoque/giro` (stock_turnover), ambos consumindo
`app/services/management.py` — mesma fonte usada por bot/dashboard/cron
(D-52).
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, delete, select, text

from app.db.session import AsyncSessionLocal, set_current_org
from app.services import management
from tests.conftest import SEED_ORG_ID
from models import Product, ProductCategory, ProductVariant

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)

        product_ids = (
            (
                await session.execute(
                    select(Product.id).where(Product.name.like("Produto Relatorio Teste%"))
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
                conn.execute(text("DELETE FROM sale_payments WHERE sale_id IN (SELECT id FROM sales WHERE organization_id = :org)"), {"org": SEED_ORG_ID})
                conn.execute(text("DELETE FROM sale_items WHERE variant_id = ANY(:ids)"), {"ids": variant_ids})
                conn.execute(text("DELETE FROM sales WHERE id NOT IN (SELECT DISTINCT sale_id FROM sale_items)"))
                conn.execute(text("DELETE FROM stock_movements WHERE variant_id = ANY(:ids)"), {"ids": variant_ids})
            eng.dispose()
            cleared = True

        if product_ids and cleared:
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.execute(
            delete(ProductCategory).where(ProductCategory.name.like("Categoria Relatorio Teste%"))
        )
        await session.commit()


def _suf() -> str:
    return str(uuid.uuid4().int % 1_000_000)


async def _criar_produto(client, auth_headers, price: str = "5.00") -> int:
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Produto Relatorio Teste {_suf()}",
            "tracks_stock": True,
            "variants": [{"name": "Único", "price": price}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["variants"][0]["id"]


async def _entrada(client, auth_headers, variant_id: int, qty: str):
    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": qty},
    )
    assert resp.status_code == 201, resp.text


async def _vender(client, auth_headers, variant_id: int, qty: str, price: str):
    total = str(round(float(qty) * float(price), 2))
    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={
            "items": [{"variant_id": variant_id, "qty": qty}],
            "payments": [{"amount": total, "method": "dinheiro"}],
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_produtos_mais_vendidos_soma_qty_e_receita(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers, price="5.00")
    await _entrada(client, auth_headers, variant_id, "20")
    await _vender(client, auth_headers, variant_id, "3", "5.00")
    await _vender(client, auth_headers, variant_id, "2", "5.00")

    today = date.today().isoformat()
    resp = await client.get(
        "/vendas/produtos-mais-vendidos",
        headers=auth_headers,
        params={"date_from": today, "date_to": today},
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["variant_id"] == variant_id)
    assert row["qty_sold"] == 5.0
    assert row["revenue"] == 25.0


@pytest.mark.asyncio
async def test_produtos_mais_vendidos_inclui_price(client, auth_headers):
    """`price` (preço atual da variação) alimenta os botões de acesso rápido."""
    variant_id = await _criar_produto(client, auth_headers, price="7.50")
    await _entrada(client, auth_headers, variant_id, "10")
    await _vender(client, auth_headers, variant_id, "1", "7.50")

    today = date.today().isoformat()
    resp = await client.get(
        "/vendas/produtos-mais-vendidos",
        headers=auth_headers,
        params={"date_from": today, "date_to": today},
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["variant_id"] == variant_id)
    assert row["price"] == 7.5


@pytest.mark.asyncio
async def test_only_active_descarta_produto_arquivado(client, auth_headers):
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Produto Relatorio Teste {_suf()}",
            "tracks_stock": True,
            "variants": [{"name": "Único", "price": "5.00"}],
        },
    )
    assert resp.status_code == 201, resp.text
    product_id = resp.json()["id"]
    variant_id = resp.json()["variants"][0]["id"]
    await _entrada(client, auth_headers, variant_id, "10")
    await _vender(client, auth_headers, variant_id, "2", "5.00")

    today = date.today().isoformat()
    base = {"date_from": today, "date_to": today}

    r = await client.get(
        "/vendas/produtos-mais-vendidos",
        headers=auth_headers,
        params={**base, "only_active": "true"},
    )
    assert any(x["variant_id"] == variant_id for x in r.json())

    arq = await client.patch(
        f"/produtos/{product_id}", headers=auth_headers, json={"active": False}
    )
    assert arq.status_code == 200, arq.text

    r_all = await client.get(
        "/vendas/produtos-mais-vendidos", headers=auth_headers, params=base
    )
    r_active = await client.get(
        "/vendas/produtos-mais-vendidos",
        headers=auth_headers,
        params={**base, "only_active": "true"},
    )
    # relatório (default): histórico completo, mesmo arquivado
    assert any(x["variant_id"] == variant_id for x in r_all.json())
    # atalhos de venda: só produto/variação ativos
    assert all(x["variant_id"] != variant_id for x in r_active.json())


@pytest.mark.asyncio
async def test_giro_estoque_calcula_turnover(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers, price="5.00")
    await _entrada(client, auth_headers, variant_id, "20")
    await _vender(client, auth_headers, variant_id, "5", "5.00")

    today = date.today().isoformat()
    resp = await client.get(
        "/estoque/giro", headers=auth_headers, params={"date_from": today, "date_to": today}
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["variant_id"] == variant_id)
    assert row["qty_sold"] == 5.0
    # saldo no início do período = 0 (nada antes da entrada de hoje), no fim = 15
    # (20 entrada - 5 venda) → média 7.5 → giro = 5 / 7.5.
    assert row["avg_stock"] == 7.5
    assert round(row["turnover"], 4) == round(5 / 7.5, 4)


@pytest.mark.asyncio
async def test_giro_estoque_ignora_variante_sem_venda_no_periodo(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers, price="5.00")
    await _entrada(client, auth_headers, variant_id, "10")

    today = date.today().isoformat()
    resp = await client.get(
        "/estoque/giro", headers=auth_headers, params={"date_from": today, "date_to": today}
    )
    assert resp.status_code == 200
    assert all(r["variant_id"] != variant_id for r in resp.json())


@pytest.mark.asyncio
async def test_reception_pode_ver_relatorios(client, auth_headers, reception_headers):
    variant_id = await _criar_produto(client, auth_headers, price="5.00")
    await _entrada(client, auth_headers, variant_id, "10")

    today = date.today().isoformat()
    resp = await client.get(
        "/vendas/produtos-mais-vendidos",
        headers=reception_headers,
        params={"date_from": today, "date_to": today},
    )
    assert resp.status_code == 200

    resp = await client.get(
        "/estoque/giro", headers=reception_headers, params={"date_from": today, "date_to": today}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_barber_nao_pode_ver_produtos_mais_vendidos_403(client, barber_headers):
    today = date.today().isoformat()
    resp = await client.get(
        "/vendas/produtos-mais-vendidos",
        headers=barber_headers,
        params={"date_from": today, "date_to": today},
    )
    assert resp.status_code == 403


async def _overview() -> dict:
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        return await management.stock_overview(session)


@pytest.mark.asyncio
async def test_stock_overview_conta_variantes_por_faixa(client, auth_headers):
    before = await _overview()

    zerada = await _criar_produto(client, auth_headers, price="5.00")
    com_estoque_1 = await _criar_produto(client, auth_headers, price="5.00")
    com_estoque_10 = await _criar_produto(client, auth_headers, price="5.00")
    await _entrada(client, auth_headers, com_estoque_1, "1")
    await _entrada(client, auth_headers, com_estoque_10, "10")

    after = await _overview()
    assert after["total_variants"] == before["total_variants"] + 3
    # `min_stock` default é 0: `zerada` (qty=0) fica <= 0 → conta em
    # below_min_count E zero_stock_count; as outras duas (qty=1 e qty=10)
    # ficam ACIMA do mínimo (0) e não contam em nenhuma das duas faixas.
    assert after["zero_stock_count"] == before["zero_stock_count"] + 1
    assert after["below_min_count"] == before["below_min_count"] + 1
    assert isinstance(after["total_value"], float)
    assert zerada != com_estoque_1 != com_estoque_10


@pytest.mark.asyncio
async def test_stock_overview_ignora_produto_sem_controle_de_estoque(client, auth_headers):
    before = await _overview()

    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Produto Relatorio Teste {_suf()}",
            "tracks_stock": False,
            "variants": [{"name": "Único", "price": "5.00"}],
        },
    )
    assert resp.status_code == 201, resp.text

    after = await _overview()
    assert after["total_variants"] == before["total_variants"]
