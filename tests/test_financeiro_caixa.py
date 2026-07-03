"""Integração de GET /financeiro/caixa — histórico de fechamento de caixa (D-59)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, set_current_org
from tests.conftest import SEED_ORG_ID
from models import CashDailyClosing

_TEST_MONTH = "2099-01"
_TEST_DATE = date(2099, 1, 15)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        row = (
            await session.execute(
                select(CashDailyClosing).where(
                    CashDailyClosing.organization_id == SEED_ORG_ID,
                    CashDailyClosing.closing_date == _TEST_DATE,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            await session.commit()


@pytest.mark.asyncio
async def test_financeiro_caixa_lista_fechamento_do_mes(client, auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        session.add(
            CashDailyClosing(
                organization_id=SEED_ORG_ID,
                closing_date=_TEST_DATE,
                opening_balance=Decimal("100.00"),
                cash_received=Decimal("200.00"),
                change_given=Decimal("0.00"),
                cash_expenses=Decimal("0.00"),
                cash_total=Decimal("200.00"),
                withdrawal=Decimal("50.00"),
                closing_balance=Decimal("250.00"),
                other_methods_received=Decimal("300.00"),
                other_methods_expenses=Decimal("0.00"),
            )
        )
        await session.commit()

    r = await client.get(
        f"/financeiro/caixa?month={_TEST_MONTH}", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["month"] == _TEST_MONTH
    assert len(body["days"]) == 1
    day = body["days"][0]
    assert day["date"] == _TEST_DATE.isoformat()
    assert day["opening_balance"] == 100.00
    assert day["closing_balance"] == 250.00
    assert day["withdrawal"] == 50.00


@pytest.mark.asyncio
async def test_financeiro_caixa_mes_sem_dados_vazio(client, auth_headers):
    r = await client.get("/financeiro/caixa?month=2010-01", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["days"] == []


@pytest.mark.asyncio
async def test_financeiro_caixa_exige_auth(client):
    r = await client.get(f"/financeiro/caixa?month={_TEST_MONTH}")
    assert r.status_code in (401, 403)
