"""Estoque — Fase 2 do módulo de Produtos/Estoque/Vendas.

Cobre lançamento manual de entrada/saída/perda, bloqueio de saldo negativo,
produto sem controle de estoque, alertas de mínimo e RBAC (reception opera
estoque, sem custo/margem exposto aqui).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, delete, text

from app.db.session import AsyncSessionLocal, set_current_org
from tests.conftest import SEED_ORG_ID
from models import Product, ProductCategory, StockMovement

# `stock_movements` é append-only (sem GRANT DELETE a `barber_app`, de
# propósito — mesmo molde de `audit_logs`). A limpeza de teste precisa da
# role dona (`ADMIN_DATABASE_URL`, mesmo padrão de `tests/test_platform_health.py`);
# sem ela, só os produtos/categorias são limpos e as movimentações de teste
# ficam acumuladas no banco de staging (inofensivo, isolado por nome).
ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        from sqlalchemy import select

        from models import ProductVariant

        product_ids = (
            (
                await session.execute(
                    select(Product.id).where(Product.name.like("Produto Estoque Teste%"))
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

        movements_cleared = not variant_ids
        if variant_ids and ADMIN_URL:
            eng = create_engine(ADMIN_URL)
            with eng.begin() as conn:
                conn.execute(
                    text("DELETE FROM stock_movements WHERE variant_id = ANY(:ids)"),
                    {"ids": variant_ids},
                )
            eng.dispose()
            movements_cleared = True

        # Sem ADMIN_DATABASE_URL, as movimentações (append-only, sem GRANT
        # DELETE a barber_app) ficam presas e o FK RESTRICT impede apagar o
        # produto/variante — deixa para a próxima limpeza com a role dona.
        if product_ids and movements_cleared:
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.execute(
            delete(ProductCategory).where(ProductCategory.name.like("Categoria Estoque Teste%"))
        )
        await session.commit()


def _suf() -> str:
    return str(uuid.uuid4().int % 1_000_000)


async def _criar_produto(client, auth_headers, *, tracks_stock: bool = True, min_stock: str = "0") -> int:
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Produto Estoque Teste {_suf()}",
            "tracks_stock": tracks_stock,
            "variants": [{"name": "Único", "price": "5.00", "min_stock": min_stock}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["variants"][0]["id"]


@pytest.mark.asyncio
async def test_entrada_ajuste_aumenta_saldo(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers)

    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "10"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["qty_delta"] == 10.0
    assert body["qty_after"] == 10.0


@pytest.mark.asyncio
async def test_saida_ajuste_diminui_saldo(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers)
    await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "10"},
    )

    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "saida_ajuste", "qty": "4"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["qty_after"] == 6.0


@pytest.mark.asyncio
async def test_saida_maior_que_saldo_409(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers)

    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "saida_ajuste", "qty": "1"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_perda_sem_motivo_422(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers)
    await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "5"},
    )

    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "perda", "qty": "1"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_perda_com_motivo_gera_movimentacao(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers)
    await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "5"},
    )

    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={
            "variant_id": variant_id,
            "movement_type": "perda",
            "qty": "2",
            "reason": "vencido",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["qty_after"] == 3.0


@pytest.mark.asyncio
async def test_produto_sem_controle_estoque_bloqueia_movimentacao_422(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers, tracks_stock=False)

    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "1"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_listar_movimentacoes_filtra_por_variante(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers)
    outro_variant_id = await _criar_produto(client, auth_headers)
    await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "3"},
    )
    await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": outro_variant_id, "movement_type": "entrada_ajuste", "qty": "9"},
    )

    resp = await client.get(
        "/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id}
    )
    assert resp.status_code == 200
    assert all(m["variant_id"] == variant_id for m in resp.json())
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_alerta_estoque_minimo(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers, min_stock="5")
    await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "3"},
    )

    resp = await client.get("/estoque/alertas", headers=auth_headers)
    assert resp.status_code == 200
    assert any(a["variant_id"] == variant_id for a in resp.json())


@pytest.mark.asyncio
async def test_reception_pode_lancar_movimentacao(client, auth_headers, reception_headers):
    variant_id = await _criar_produto(client, auth_headers)

    resp = await client.post(
        "/estoque/movimentacoes",
        headers=reception_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "1"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_barber_nao_pode_ver_estoque_403(client, barber_headers):
    resp = await client.get("/estoque/movimentacoes", headers=barber_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_rls_isola_movimentacao_entre_orgs(client, auth_headers):
    variant_id = await _criar_produto(client, auth_headers)
    resp = await client.post(
        "/estoque/movimentacoes",
        headers=auth_headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": "1"},
    )
    movement_id = resp.json()["id"]

    other_org_id = SEED_ORG_ID + 999_000
    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org_id)
        from sqlalchemy import select

        rows = (
            await session.execute(select(StockMovement).where(StockMovement.id == movement_id))
        ).scalars().all()
        assert rows == []
