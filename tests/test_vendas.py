"""Venda de produtos — Fase 3 do módulo de Produtos/Estoque/Vendas.

Cobre baixa automática de estoque na confirmação da venda, bloqueio de saldo
insuficiente, produto sem controle de estoque (sem movimentação), cancelamento
com reversão de estoque, venda anexada a um atendimento (sem tocar
`AppointmentItem`), RBAC e isolamento por RLS.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, delete, select, text

from app.db.session import AsyncSessionLocal, set_current_org
from tests.conftest import SEED_ORG_ID
from models import (
    Appointment,
    AppointmentStatus,
    Client,
    Product,
    ProductCategory,
    ProductVariant,
    Sale,
    Unit,
)

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
                    select(Product.id).where(Product.name.like("Produto Venda Teste%"))
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

        cleared_sales = not variant_ids
        if variant_ids and ADMIN_URL:
            eng = create_engine(ADMIN_URL)
            with eng.begin() as conn:
                sale_ids = [
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT DISTINCT sale_id FROM sale_items WHERE variant_id = ANY(:ids)"
                        ),
                        {"ids": variant_ids},
                    )
                ]
                if sale_ids:
                    conn.execute(
                        text("DELETE FROM sale_payments WHERE sale_id = ANY(:ids)"),
                        {"ids": sale_ids},
                    )
                    conn.execute(
                        text("DELETE FROM sale_items WHERE sale_id = ANY(:ids)"),
                        {"ids": sale_ids},
                    )
                    conn.execute(
                        text("DELETE FROM sales WHERE id = ANY(:ids)"), {"ids": sale_ids}
                    )
                conn.execute(
                    text("DELETE FROM stock_movements WHERE variant_id = ANY(:ids)"),
                    {"ids": variant_ids},
                )
            eng.dispose()
            cleared_sales = True

        if product_ids and cleared_sales:
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.execute(
            delete(ProductCategory).where(ProductCategory.name.like("Categoria Venda Teste%"))
        )
        await session.execute(delete(Appointment).where(Appointment.display_number.between(900_000, 999_999)))
        await session.execute(delete(Client).where(Client.name.like("Cliente Venda Teste%")))
        await session.commit()


async def _criar_produto(
    client, auth_headers, *, tracks_stock: bool = True, price: str = "10.00", stock: str = "0"
) -> tuple[int, int]:
    """Cria produto com 1 variante e, se rastreado, dá entrada de estoque. Retorna (product_id, variant_id)."""
    resp = await client.post(
        "/produtos",
        headers=auth_headers,
        json={
            "name": f"Produto Venda Teste {_suf()}",
            "tracks_stock": tracks_stock,
            "variants": [{"name": "Único", "price": price}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    variant_id = body["variants"][0]["id"]

    if tracks_stock and Decimal(stock) > 0:
        resp = await client.post(
            "/estoque/movimentacoes",
            headers=auth_headers,
            json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": stock},
        )
        assert resp.status_code == 201, resp.text

    return body["id"], variant_id


@pytest.mark.asyncio
async def test_criar_venda_baixa_estoque(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers, price="5.00", stock="10")

    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={
            "items": [{"variant_id": variant_id, "qty": "3"}],
            "payments": [{"amount": "15.00", "method": "dinheiro"}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "concluida"
    assert body["total_amount"] == 15.0
    assert body["items"][0]["unit_price_charged"] == 5.0

    mov_resp = await client.get(
        "/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id}
    )
    assert mov_resp.status_code == 200
    saida = [m for m in mov_resp.json() if m["movement_type"] == "saida_venda"]
    assert len(saida) == 1
    assert saida[0]["qty_after"] == 7.0


@pytest.mark.asyncio
async def test_pagamento_nao_bate_com_total_422(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers, price="5.00", stock="10")

    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={
            "items": [{"variant_id": variant_id, "qty": "2"}],
            "payments": [{"amount": "9.00", "method": "pix"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_estoque_insuficiente_409(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers, price="5.00", stock="1")

    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={
            "items": [{"variant_id": variant_id, "qty": "5"}],
            "payments": [{"amount": "25.00", "method": "cartao"}],
        },
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_produto_sem_controle_estoque_nao_gera_movimentacao(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers, tracks_stock=False, price="4.00")

    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={
            "items": [{"variant_id": variant_id, "qty": "100"}],
            "payments": [{"amount": "400.00", "method": "pix"}],
        },
    )
    assert resp.status_code == 201, resp.text

    mov_resp = await client.get(
        "/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id}
    )
    assert mov_resp.json() == []


@pytest.mark.asyncio
async def test_cancelar_venda_estorna_estoque(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers, price="5.00", stock="10")

    venda_resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={
            "items": [{"variant_id": variant_id, "qty": "4"}],
            "payments": [{"amount": "20.00", "method": "dinheiro"}],
        },
    )
    sale_id = venda_resp.json()["id"]

    cancel_resp = await client.patch(f"/vendas/{sale_id}/cancelar", headers=auth_headers)
    assert cancel_resp.status_code == 200, cancel_resp.text
    assert cancel_resp.json()["status"] == "cancelada"

    mov_resp = await client.get(
        "/estoque/movimentacoes", headers=auth_headers, params={"variant_id": variant_id}
    )
    ultima = mov_resp.json()[0]
    assert ultima["qty_after"] == 10.0

    cancel_de_novo = await client.patch(f"/vendas/{sale_id}/cancelar", headers=auth_headers)
    assert cancel_de_novo.status_code == 409


@pytest.mark.asyncio
async def test_venda_anexada_a_atendimento_nao_altera_appointment(client, auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        unit = (await session.execute(select(Unit).limit(1))).scalar_one()
        suf = uuid.uuid4().int % 1_000_000
        cliente = Client(
            organization_id=SEED_ORG_ID,
            name=f"Cliente Venda Teste {suf}",
            phone_e164=f"+5563{suf:08d}"[:15],
        )
        session.add(cliente)
        await session.flush()
        appt = Appointment(
            organization_id=SEED_ORG_ID,
            unit_id=unit.id,
            client_id=cliente.id,
            display_number=900_000 + (suf % 90_000),
            start_at=datetime(2099, 8, 1, 14, 0, tzinfo=timezone.utc),
            end_at=datetime(2099, 8, 1, 14, 30, tzinfo=timezone.utc),
            status=AppointmentStatus.agendado,
            total_amount=Decimal("0"),
        )
        session.add(appt)
        await session.flush()
        appointment_id = appt.id
        client_id = cliente.id
        await session.commit()

    _, variant_id = await _criar_produto(client, auth_headers, price="6.00", stock="5")

    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={
            "client_id": client_id,
            "appointment_id": appointment_id,
            "items": [{"variant_id": variant_id, "qty": "1"}],
            "payments": [{"amount": "6.00", "method": "pix"}],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["appointment_id"] == appointment_id

    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        appt_after = (
            await session.execute(select(Appointment).where(Appointment.id == appointment_id))
        ).scalar_one()
        assert appt_after.status == "agendado"


@pytest.mark.asyncio
async def test_reception_pode_criar_venda_mas_nao_cancelar(client, auth_headers, reception_headers):
    _, variant_id = await _criar_produto(client, auth_headers, price="5.00", stock="10")

    resp = await client.post(
        "/vendas",
        headers=reception_headers,
        json={
            "items": [{"variant_id": variant_id, "qty": "1"}],
            "payments": [{"amount": "5.00", "method": "dinheiro"}],
        },
    )
    assert resp.status_code == 201, resp.text
    sale_id = resp.json()["id"]

    cancel_resp = await client.patch(f"/vendas/{sale_id}/cancelar", headers=reception_headers)
    assert cancel_resp.status_code == 403


@pytest.mark.asyncio
async def test_barber_nao_pode_ver_vendas_403(client, barber_headers):
    resp = await client.get("/vendas", headers=barber_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_rls_isola_venda_entre_orgs(client, auth_headers):
    _, variant_id = await _criar_produto(client, auth_headers, price="5.00", stock="10")
    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={
            "items": [{"variant_id": variant_id, "qty": "1"}],
            "payments": [{"amount": "5.00", "method": "dinheiro"}],
        },
    )
    sale_id = resp.json()["id"]

    other_org_id = SEED_ORG_ID + 999_000
    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org_id)
        rows = (await session.execute(select(Sale).where(Sale.id == sale_id))).scalars().all()
        assert rows == []
