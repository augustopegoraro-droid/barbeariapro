"""Integração das sugestões de compra de produto (D-98).

Molde de `tests/test_reschedule_integration.py` (D-57), estendendo o mesmo
padrão de "solicitação pendente de aprovação" para compras: barbeiro/recepção
sugerem, gestor decide. Usa `auth_headers` (owner = gestor), `barber_headers`
e `reception_headers` do conftest; skip gracioso sem DB semeado.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.session import AsyncSessionLocal, set_current_org

pytestmark = pytest.mark.asyncio

SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_purchase_requests():
    """Zera as sugestões de compra do tenant semeado antes/depois de cada teste
    (mesmo motivo/molde de `_clean_reschedule`: sem isso os pendentes acumulam
    entre execuções e tornam contagens/filtros não-determinísticos)."""

    async def _wipe() -> None:
        async with AsyncSessionLocal() as s:
            await set_current_org(s, SEED_ORG_ID)
            await s.execute(text("DELETE FROM product_purchase_requests"))
            await s.commit()

    try:
        await _wipe()
    except Exception:
        pass
    yield
    try:
        await _wipe()
    except Exception:
        pass


async def test_barbeiro_cria_pedido_por_nome(client, barber_headers):
    r = await client.post(
        "/compras-sugeridas",
        json={"product_name": f"Shampoo Teste {uuid.uuid4().hex[:8]}", "motivo": "acabando"},
        headers=barber_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pendente"
    assert body["source"] == "app"
    assert body["product_name"]


async def test_recepcao_cria_pedido_por_nome(client, reception_headers):
    r = await client.post(
        "/compras-sugeridas",
        json={"product_name": f"Cera Teste {uuid.uuid4().hex[:8]}"},
        headers=reception_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pendente"


async def test_gestor_lista_e_conta_pendentes(client, barber_headers, auth_headers):
    await client.post(
        "/compras-sugeridas",
        json={"product_name": f"Produto Contagem {uuid.uuid4().hex[:8]}"},
        headers=barber_headers,
    )
    r = await client.get("/compras-sugeridas?status=pendente", headers=auth_headers)
    assert r.status_code == 200, r.text
    lst = r.json()
    assert isinstance(lst, list) and len(lst) >= 1
    assert all(item["status"] == "pendente" for item in lst)
    c = await client.get("/compras-sugeridas/pendentes/count", headers=auth_headers)
    assert c.status_code == 200, c.text
    assert c.json()["count"] >= 1


async def test_barbeiro_nao_pode_listar(client, barber_headers):
    r = await client.get("/compras-sugeridas", headers=barber_headers)
    assert r.status_code == 403, r.text


async def test_barbeiro_nao_pode_aprovar(client, barber_headers):
    created = await client.post(
        "/compras-sugeridas",
        json={"product_name": f"Produto Aprovar {uuid.uuid4().hex[:8]}"},
        headers=barber_headers,
    )
    rid = created.json()["id"]
    r = await client.patch(
        f"/compras-sugeridas/{rid}", json={"approve": True}, headers=barber_headers
    )
    assert r.status_code == 403, r.text


async def test_gestor_aprova_e_reaprovar_da_conflito(client, barber_headers, auth_headers):
    created = await client.post(
        "/compras-sugeridas",
        json={"product_name": f"Produto Reaprovar {uuid.uuid4().hex[:8]}"},
        headers=barber_headers,
    )
    rid = created.json()["id"]

    ok = await client.patch(
        f"/compras-sugeridas/{rid}",
        json={"approve": True, "note": "beleza"},
        headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "aprovada"
    assert body["reviewed_by_user_id"] is not None
    assert body["reviewed_at"] is not None

    again = await client.patch(
        f"/compras-sugeridas/{rid}", json={"approve": False}, headers=auth_headers
    )
    assert again.status_code == 409, again.text


async def test_criar_sem_produto_nem_variant_da_422(client, barber_headers):
    r = await client.post("/compras-sugeridas", json={"motivo": "sem alvo"}, headers=barber_headers)
    assert r.status_code == 422, r.text


async def test_criar_quantidade_zero_da_422(client, barber_headers):
    r = await client.post(
        "/compras-sugeridas",
        json={"product_name": "Produto Qtd Zero", "quantidade_sugerida": "0"},
        headers=barber_headers,
    )
    assert r.status_code == 422, r.text


async def test_listar_status_invalido_da_422(client, auth_headers):
    r = await client.get("/compras-sugeridas?status=bogus", headers=auth_headers)
    assert r.status_code == 422, r.text


async def test_listar_status_vazio_traz_todos(client, barber_headers, auth_headers):
    created = await client.post(
        "/compras-sugeridas",
        json={"product_name": f"Produto Status Vazio {uuid.uuid4().hex[:8]}"},
        headers=barber_headers,
    )
    rid = created.json()["id"]
    ok = await client.patch(
        f"/compras-sugeridas/{rid}", json={"approve": True}, headers=auth_headers
    )
    assert ok.status_code == 200, ok.text
    r = await client.get("/compras-sugeridas?status=", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(item["status"] == "aprovada" for item in r.json())


async def test_listar_ordena_deterministico_no_empate():
    """3 pedidos criados na MESMA transação compartilham `created_at`
    (func.now() é constante na transação); sem desempate por `id` a ordem
    entre eles é indefinida. `list_requests` deve devolvê-los sempre em id DESC."""
    from app.services.purchase_requests import create_request, list_requests

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        ids = []
        for i in range(3):
            req = await create_request(
                s,
                organization_id=SEED_ORG_ID,
                requested_by_user_id=None,
                product_name=f"Produto Empate {i} {uuid.uuid4().hex[:6]}",
            )
            ids.append(req.id)
        rows = await list_requests(s, status="pendente")
        got = [r.id for r in rows if r.id in ids]

    assert got == sorted(ids, reverse=True), got
