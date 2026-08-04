"""Produtos/Estoque/Vendas — Fase 4: `financial_summary()` passa a somar receita
de venda de produto, separada da receita de serviço (nunca misturada, D-91).

Cobre `app/services/management.py::product_sales_summary` diretamente (molde
`tests/test_commission_transfers.py`): venda concluída entra, venda cancelada
não entra, lucro = receita - custo (snapshot de `cost_avg` no momento da
venda).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, delete, select, text

from app.db.session import AsyncSessionLocal, set_current_org
from app.services.management import financial_summary, product_sales_summary
from tests.conftest import SEED_ORG_ID
from models import Product, ProductCategory, Sale, SaleItem, SaleStatus, Unit

_DAY = date(2099, 9, 1)
_CREATED_AT = datetime(2099, 9, 1, 14, 0, tzinfo=timezone.utc)

# `sales`/`sale_items`/`sale_payments` são registros financeiros (sem GRANT
# DELETE a `barber_app`, de propósito — molde `stock_movements`/`audit_logs`:
# cancela-se, nunca se apaga). A limpeza de teste precisa da role dona
# (`ADMIN_DATABASE_URL`, mesmo padrão de `tests/test_estoque.py`); sem ela, as
# vendas de teste ficam acumuladas no banco de staging (inofensivo, isolado
# por data em 2099).
ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")


def _suf() -> str:
    return str(uuid.uuid4().int % 1_000_000)


async def _cleanup():
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        product_ids = (
            (
                await session.execute(
                    select(Product.id).where(Product.name.like("Produto D91 Teste%"))
                )
            )
            .scalars()
            .all()
        )
        sale_ids = (
            (await session.execute(select(Sale.id).where(Sale.created_at >= _CREATED_AT)))
            .scalars()
            .all()
        )

        cleared_sales = not sale_ids
        if sale_ids and ADMIN_URL:
            eng = create_engine(ADMIN_URL)
            with eng.begin() as conn:
                conn.execute(text("DELETE FROM sale_payments WHERE sale_id = ANY(:ids)"), {"ids": sale_ids})
                conn.execute(text("DELETE FROM sale_items WHERE sale_id = ANY(:ids)"), {"ids": sale_ids})
                conn.execute(text("DELETE FROM sales WHERE id = ANY(:ids)"), {"ids": sale_ids})
            eng.dispose()
            cleared_sales = True

        if product_ids and cleared_sales:
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.execute(
            delete(ProductCategory).where(ProductCategory.name.like("Categoria D91 Teste%"))
        )
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_fixture():
    await _cleanup()
    yield
    await _cleanup()


async def _seed_sale(session, *, status: SaleStatus, price="10.00", cost="4.00", qty="2"):
    unit = (await session.execute(select(Unit).limit(1))).scalar_one()
    suf = uuid.uuid4().int % 1_000_000
    product = Product(
        organization_id=SEED_ORG_ID, name=f"Produto D91 Teste {suf}", tracks_stock=False
    )
    session.add(product)
    await session.flush()

    from models import ProductVariant

    variant = ProductVariant(
        organization_id=SEED_ORG_ID,
        product_id=product.id,
        name="Único",
        price=Decimal(price),
        cost_avg=Decimal(cost),
    )
    session.add(variant)
    await session.flush()

    sale = Sale(
        organization_id=SEED_ORG_ID,
        unit_id=unit.id,
        status=status,
        total_amount=Decimal(price) * Decimal(qty),
        created_at=_CREATED_AT,
    )
    session.add(sale)
    await session.flush()

    item = SaleItem(
        organization_id=SEED_ORG_ID,
        sale_id=sale.id,
        variant_id=variant.id,
        qty=Decimal(qty),
        unit_price_charged=Decimal(price),
        unit_cost_snapshot=Decimal(cost),
    )
    session.add(item)
    await session.flush()
    return sale


@pytest.mark.asyncio
async def test_product_sales_summary_soma_so_vendas_concluidas():
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        await _seed_sale(session, status=SaleStatus.concluida, price="10.00", cost="4.00", qty="2")
        await _seed_sale(session, status=SaleStatus.cancelada, price="50.00", cost="20.00", qty="1")
        await session.commit()
        await set_current_org(session, SEED_ORG_ID)

        data = await product_sales_summary(session, _DAY, _DAY)
        assert data["revenue"] == 20.0
        assert data["cost"] == 8.0
        assert data["profit"] == 12.0
        assert data["sale_count"] == 1


@pytest.mark.asyncio
async def test_financial_summary_inclui_products_sem_misturar_com_revenue():
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        await _seed_sale(session, status=SaleStatus.concluida, price="7.00", cost="3.00", qty="3")
        await session.commit()
        await set_current_org(session, SEED_ORG_ID)

        data = await financial_summary(session, _DAY, _DAY)
        assert data["products"]["revenue"] == 21.0
        assert data["products"]["profit"] == 12.0
        # `revenue`/`net` (serviço) não são afetados pela venda de produto.
        assert "revenue" in data and "products" in data
