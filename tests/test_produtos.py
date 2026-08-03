"""Catálogo de produtos — Fase 1 do módulo de Produtos/Estoque/Vendas.

Cobre CRUD de categorias/produtos/variações, RBAC (owner cadastra, reception só
vê) e isolamento RLS entre organizações.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal, set_current_org
from tests.conftest import SEED_ORG_ID
from models import Product, ProductCategory


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        await session.execute(delete(Product).where(Product.name.like("Produto Teste%")))
        await session.execute(
            delete(ProductCategory).where(ProductCategory.name.like("Categoria Teste%"))
        )
        await session.commit()


def _suf() -> str:
    return str(uuid.uuid4().int % 1_000_000)


# ─── Categorias ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_criar_categoria_e_listar(client, auth_headers):
    name = f"Categoria Teste {_suf()}"
    resp = await client.post(
        "/produtos/categorias", headers=auth_headers, json={"name": name, "position": 2}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == name

    listed = await client.get("/produtos/categorias", headers=auth_headers)
    assert listed.status_code == 200
    assert any(c["name"] == name for c in listed.json())


@pytest.mark.asyncio
async def test_criar_categoria_duplicada_409(client, auth_headers):
    name = f"Categoria Teste {_suf()}"
    first = await client.post("/produtos/categorias", headers=auth_headers, json={"name": name})
    assert first.status_code == 201

    dup = await client.post("/produtos/categorias", headers=auth_headers, json={"name": name})
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_arquivar_categoria_via_patch(client, auth_headers):
    name = f"Categoria Teste {_suf()}"
    created = await client.post("/produtos/categorias", headers=auth_headers, json={"name": name})
    cat_id = created.json()["id"]

    patched = await client.patch(
        f"/produtos/categorias/{cat_id}", headers=auth_headers, json={"active": False}
    )
    assert patched.status_code == 200
    assert patched.json()["active"] is False

    listed = await client.get("/produtos/categorias", headers=auth_headers)
    assert all(c["id"] != cat_id for c in listed.json())

    listed_all = await client.get(
        "/produtos/categorias", headers=auth_headers, params={"include_inactive": "true"}
    )
    assert any(c["id"] == cat_id for c in listed_all.json())


@pytest.mark.asyncio
async def test_categoria_reception_nao_pode_criar_403(client, reception_headers):
    resp = await client.post(
        "/produtos/categorias",
        headers=reception_headers,
        json={"name": f"Categoria Teste {_suf()}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_categoria_reception_pode_ver(client, reception_headers):
    resp = await client.get("/produtos/categorias", headers=reception_headers)
    assert resp.status_code == 200


# ─── Produtos / variações ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_criar_produto_sem_variants_gera_variante_unico(client, auth_headers):
    name = f"Produto Teste {_suf()}"
    resp = await client.post(
        "/produtos", headers=auth_headers, json={"name": name, "price": "5.50"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == name
    assert len(body["variants"]) == 1
    assert body["variants"][0]["name"] == "Único"
    assert body["variants"][0]["price"] == 5.5
    assert body["tracks_stock"] is True


@pytest.mark.asyncio
async def test_criar_produto_sem_price_nem_variants_422(client, auth_headers):
    resp = await client.post(
        "/produtos", headers=auth_headers, json={"name": f"Produto Teste {_suf()}"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_criar_produto_com_variacoes_explicitas(client, auth_headers):
    name = f"Produto Teste {_suf()}"
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": name,
            "tracks_stock": False,
            "variants": [
                {"name": "300ml", "price": "6.00"},
                {"name": "500ml", "price": "8.00"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tracks_stock"] is False
    assert {v["name"] for v in body["variants"]} == {"300ml", "500ml"}


@pytest.mark.asyncio
async def test_produto_sem_controle_estoque_flag_persiste(client, auth_headers):
    name = f"Produto Teste {_suf()}"
    created = await client.post(
        "/produtos",
        headers=auth_headers,
        json={"name": name, "price": "3.00", "tracks_stock": False},
    )
    assert created.status_code == 201
    product_id = created.json()["id"]

    got = await client.get(f"/produtos/{product_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["tracks_stock"] is False


@pytest.mark.asyncio
async def test_adicionar_variacao_e_atualizar(client, auth_headers):
    name = f"Produto Teste {_suf()}"
    created = await client.post(
        "/produtos", headers=auth_headers, json={"name": name, "price": "10.00"}
    )
    product_id = created.json()["id"]

    variant = await client.post(
        f"/produtos/{product_id}/variacoes",
        headers=auth_headers,
        json={"name": "Grande", "price": "15.00"},
    )
    assert variant.status_code == 201, variant.text
    variant_id = variant.json()["id"]

    updated = await client.patch(
        f"/produtos/variacoes/{variant_id}", headers=auth_headers, json={"price": "17.50"}
    )
    assert updated.status_code == 200
    assert updated.json()["price"] == 17.5

    got = await client.get(f"/produtos/{product_id}", headers=auth_headers)
    assert len(got.json()["variants"]) == 2


@pytest.mark.asyncio
async def test_arquivar_produto_via_patch(client, auth_headers):
    name = f"Produto Teste {_suf()}"
    created = await client.post(
        "/produtos", headers=auth_headers, json={"name": name, "price": "10.00"}
    )
    product_id = created.json()["id"]

    patched = await client.patch(
        f"/produtos/{product_id}", headers=auth_headers, json={"active": False}
    )
    assert patched.status_code == 200
    assert patched.json()["active"] is False

    listed = await client.get("/produtos", headers=auth_headers)
    assert all(p["id"] != product_id for p in listed.json())


@pytest.mark.asyncio
async def test_produto_categoria_inexistente_404(client, auth_headers):
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={"name": f"Produto Teste {_suf()}", "price": "1.00", "category_id": 999999},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_produto_reception_nao_pode_criar_403(client, reception_headers):
    resp = await client.post(
        "/produtos",
        headers=reception_headers,
        json={"name": f"Produto Teste {_suf()}", "price": "1.00"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_produto_reception_pode_listar(client, reception_headers):
    resp = await client.get("/produtos", headers=reception_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_produto_nao_encontrado_404(client, auth_headers):
    resp = await client.get("/produtos/999999", headers=auth_headers)
    assert resp.status_code == 404


# ─── RLS ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rls_isola_produto_entre_orgs():
    """Um produto criado sob o tenant da org 1 não aparece numa sessão sob
    outro `app.current_org_id` (molde de isolamento multi-tenant)."""
    other_org_id = SEED_ORG_ID + 999_000
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        category = ProductCategory(
            organization_id=SEED_ORG_ID, name=f"Categoria Teste {_suf()}"
        )
        session.add(category)
        await session.flush()
        category_id = category.id
        await session.commit()

    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org_id)
        from sqlalchemy import select

        rows = (
            await session.execute(
                select(ProductCategory).where(ProductCategory.id == category_id)
            )
        ).scalars().all()
        assert rows == []
