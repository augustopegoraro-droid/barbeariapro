"""Integração de GET /financeiro/dre (despesa por conta) e /financeiro/pagamentos.

Consumo analítico dos imports da Trinks: o drill-down/Top-N de despesas do DRE
(D-65) e o relatório de mix de formas / custo de cartão (D-63). Usa competência/
movimentação em 2099 para isolar das linhas de seed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal, set_current_org
from tests.conftest import SEED_ORG_ID
from models import DreMonthlyLine, PaymentTransaction

_DRE_MONTH = date(2099, 1, 1)
_PAG_DATE = date(2099, 1, 15)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        await session.execute(
            delete(DreMonthlyLine).where(
                DreMonthlyLine.organization_id == SEED_ORG_ID,
                DreMonthlyLine.competence_month >= _DRE_MONTH,
            )
        )
        await session.execute(
            delete(PaymentTransaction).where(
                PaymentTransaction.organization_id == SEED_ORG_ID,
                PaymentTransaction.movement_date >= _DRE_MONTH,
            )
        )
        await session.commit()


def _seed_dre(session) -> None:
    rows = [
        ("receita", None, "Serviços", "1000.00"),
        ("despesa", "fixa", "Aluguel", "300.00"),
        ("despesa", "fixa", "Energia", "100.00"),
        ("despesa", "variavel", "Compra de Produto", "200.00"),
        ("despesa", "pessoal", "Vale/Adiantamento Profissional", "400.00"),
    ]
    for section, sub, item, amount in rows:
        session.add(
            DreMonthlyLine(
                organization_id=SEED_ORG_ID,
                competence_month=_DRE_MONTH,
                section=section,
                subgroup=sub,
                line_item=item,
                amount=Decimal(amount),
            )
        )


def _seed_pagamentos(session) -> None:
    rows = [
        ("Crédito", "Visa", "100.00", "-3.00", "97.00"),
        ("Crédito", "Mastercard", "100.00", "-2.00", "98.00"),
        ("PIX", "PIX", "200.00", "0.00", "200.00"),
        ("Débito", "Visa Electron", "50.00", "-1.00", "49.00"),
        ("À Vista", "Dinheiro", "30.00", "0.00", "30.00"),
    ]
    for ptype, method, paid, fee, recv in rows:
        session.add(
            PaymentTransaction(
                organization_id=SEED_ORG_ID,
                movement_date=_PAG_DATE,
                payment_type=ptype,
                payment_method=method,
                amount_paid=Decimal(paid),
                operator_discount_amount=Decimal(fee),
                amount_to_receive=Decimal(recv),
            )
        )


# ─── DRE: despesa por conta ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dre_despesa_por_item(client, auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        _seed_dre(session)
        await session.commit()

    r = await client.get(
        "/financeiro/dre?inicio=2099-01&fim=2099-01", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["receita_total"] == 1000.0
    assert body["despesa_total"] == 1000.0

    itens = body["despesa_por_item"]
    assert len(itens) == 4  # só as contas de despesa (receita não entra)
    totais = [i["total"] for i in itens]
    assert totais == sorted(totais, reverse=True)  # ordenado por total desc
    assert itens[0]["item"] == "Vale/Adiantamento Profissional"
    assert itens[0]["subgrupo"] == "pessoal"
    assert itens[0]["total"] == 400.0
    # a soma das contas fecha com o total de despesa (sem dupla contagem)
    assert round(sum(i["total"] for i in itens), 2) == 1000.0


@pytest.mark.asyncio
async def test_dre_exige_auth(client):
    r = await client.get("/financeiro/dre")
    assert r.status_code in (401, 403)


# ─── Pagamentos: mix / custo de cartão / evolução ─────────────────────────────


@pytest.mark.asyncio
async def test_pagamentos_mix_totais_e_taxa(client, auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        _seed_pagamentos(session)
        await session.commit()

    r = await client.get(
        "/financeiro/pagamentos?inicio=2099-01&fim=2099-01", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    b = r.json()

    assert b["count"] == 5
    assert b["total_recebido"] == 480.0
    assert b["total_taxa"] == -6.0
    assert b["total_liquido"] == 474.0
    assert b["ticket_medio"] == 96.0
    assert b["pix_pct"] == round(200 / 480 * 100, 2)

    por_tipo = {t["tipo"]: t for t in b["por_tipo"]}
    assert por_tipo["Crédito"]["count"] == 2
    assert por_tipo["Crédito"]["recebido"] == 200.0
    assert por_tipo["Crédito"]["taxa"] == -5.0
    assert por_tipo["PIX"]["recebido"] == 200.0
    assert por_tipo["PIX"]["taxa"] == 0.0

    por_band = {x["bandeira"]: x for x in b["por_bandeira"]}
    assert por_band["Visa"]["taxa_pct"] == 3.0       # 3 / 100
    assert por_band["Visa Electron"]["taxa_pct"] == 2.0  # 1 / 50
    assert por_band["PIX"]["taxa_pct"] == 0.0
    assert por_band["Dinheiro"]["taxa_pct"] == 0.0

    assert len(b["por_mes"]) == 1
    assert b["por_mes"][0]["month"] == "2099-01"
    assert b["por_mes"][0]["recebido"] == 480.0
    assert b["por_mes"][0]["taxa"] == -6.0


@pytest.mark.asyncio
async def test_pagamentos_periodo_exclui_fora_do_range(client, auth_headers):
    """Limite superior é exclusivo (mês seguinte): fim=2098-12 não pega 2099-01."""
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        _seed_pagamentos(session)
        await session.commit()

    r = await client.get(
        "/financeiro/pagamentos?inicio=2098-01&fim=2098-12", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["count"] == 0
    assert b["total_recebido"] == 0.0
    assert b["por_tipo"] == []
    assert b["por_mes"] == []


@pytest.mark.asyncio
async def test_pagamentos_exige_auth(client):
    r = await client.get("/financeiro/pagamentos?inicio=2099-01&fim=2099-01")
    assert r.status_code in (401, 403)
