"""Despesas ricas + contas a pagar + despesas recorrentes (D-102).

Cobre: campos ricos (forma de pagamento, subgrupo, beneficiário) persistem no
`POST`; `GET /financeiro/despesas` com filtros `month`/`status`/`subgroup`;
`overdue` derivado; `PATCH` edita campos; `mark_paid` de `a_pagar` em DINHEIRO
com caixa aberto → movimento `despesa`; `mark_paid` em dinheiro sem caixa +
enforcement ligado → 409 `cash_register_closed`; `unmark_paid` compensa o caixa
com `ajuste`; CRUD de recorrências; `POST /internal/expenses/run` materializa e
a 2ª chamada é no-op (idempotência); RLS entre orgs; RBAC (barbeiro/recepção
403 — despesa é manager-only).

`cash_movements`/`cash_sessions`/`expense_recurrences` são append-only ou
sem DELETE para `barber_app` — a limpeza usa `ADMIN_DATABASE_URL`, molde
`tests/test_caixa.py`.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text, update

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from models import Expense, ExpenseRecurrence, Organization
from tests.conftest import SEED_ORG_ID

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
FUTURE_MONTH = "2099-06"

pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason="ADMIN_DATABASE_URL necessário para limpar tabelas append-only/sem-DELETE.",
)


def _tag() -> str:
    return f"D102 {uuid.uuid4().hex[:8]}"


async def _set_enforced(value: bool) -> None:
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        await session.execute(
            update(Organization)
            .where(Organization.id == SEED_ORG_ID)
            .values(cash_register_enforced=value)
        )
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    eng = create_engine(ADMIN_URL)
    with eng.begin() as conn:
        d = {"o": SEED_ORG_ID}
        conn.execute(text("DELETE FROM cash_movements WHERE organization_id = :o"), d)
        conn.execute(text("DELETE FROM cash_sessions WHERE organization_id = :o"), d)
        conn.execute(
            text(
                "DELETE FROM expenses WHERE organization_id = :o AND ("
                " competence_month >= DATE '2099-01-01'"
                " OR recurrence_id IN (SELECT id FROM expense_recurrences WHERE description LIKE 'D102 %')"
                " OR category_id IN (SELECT id FROM expense_categories WHERE name LIKE 'D102 %'))"
            ),
            d,
        )
        conn.execute(
            text("DELETE FROM expense_recurrences WHERE organization_id = :o AND description LIKE 'D102 %'"),
            d,
        )
        conn.execute(
            text("DELETE FROM expense_categories WHERE organization_id = :o AND name LIKE 'D102 %'"),
            d,
        )
        conn.execute(
            text("UPDATE organizations SET cash_register_enforced = false WHERE id = :o"), d
        )
    eng.dispose()


async def _criar(client, headers, **over) -> dict:
    body = {
        "category": _tag(),
        "amount": 100.0,
        "month": FUTURE_MONTH,
        "status": "pago",
        **over,
    }
    resp = await client.post("/financeiro/despesas", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _abrir_caixa(client, headers, opening="200.00"):
    resp = await client.post("/caixa/abrir", headers=headers, json={"opening_float": opening})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _bot_headers():
    if not settings.bot_api_key or not settings.bot_organization_id:
        pytest.skip("BOT_API_KEY/BOT_ORGANIZATION_ID não configurados.")
    return {"X-Bot-Token": settings.bot_api_key}


# ─── campos ricos + listagem/filtros ────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_persiste_campos_ricos(client, auth_headers):
    data = await _criar(
        client,
        auth_headers,
        amount=400.0,
        method="pix",
        subgroup="pessoal",
        payee="João Contador",
        note="Honorários",
    )
    assert data["method"] == "pix"
    assert data["subgroup"] == "pessoal"
    assert data["payee"] == "João Contador"
    assert data["status"] == "pago"
    assert data["paid_at"] is not None


@pytest.mark.asyncio
async def test_get_despesas_filtra_status_e_subgroup(client, auth_headers):
    await _criar(client, auth_headers, subgroup="fixa", status="pago", method="transferencia")
    await _criar(
        client, auth_headers, subgroup="variavel", status="a_pagar", due_date="2099-06-05"
    )

    r = await client.get(
        "/financeiro/despesas", headers=auth_headers, params={"month": FUTURE_MONTH}
    )
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = await client.get(
        "/financeiro/despesas",
        headers=auth_headers,
        params={"month": FUTURE_MONTH, "status": "a_pagar"},
    )
    assert [e["status"] for e in r.json()] == ["a_pagar"]

    r = await client.get(
        "/financeiro/despesas",
        headers=auth_headers,
        params={"month": FUTURE_MONTH, "subgroup": "fixa"},
    )
    assert len(r.json()) == 1 and r.json()[0]["subgroup"] == "fixa"

    r = await client.get(
        "/financeiro/despesas",
        headers=auth_headers,
        params={"month": FUTURE_MONTH, "status": "xpto"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_overdue_derivado(client, auth_headers):
    # vencida: a_pagar com due_date no passado
    await _criar(
        client, auth_headers, status="a_pagar", due_date="2000-01-01", month=FUTURE_MONTH
    )
    r = await client.get(
        "/financeiro/despesas",
        headers=auth_headers,
        params={"month": FUTURE_MONTH, "status": "a_pagar"},
    )
    assert r.json()[0]["overdue"] is True


# ─── PATCH / marcar paga / desmarcar ────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_edita_campos(client, auth_headers):
    d = await _criar(client, auth_headers, subgroup="fixa")
    r = await client.patch(
        f"/financeiro/despesas/{d['id']}",
        headers=auth_headers,
        json={"note": "revisado", "subgroup": "impostos", "payee": "Receita Federal"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "revisado"
    assert r.json()["subgroup"] == "impostos"
    assert r.json()["payee"] == "Receita Federal"


@pytest.mark.asyncio
async def test_mark_paid_dinheiro_com_caixa_gera_movimento(client, auth_headers):
    await _abrir_caixa(client, auth_headers, "200.00")
    d = await _criar(
        client, auth_headers, amount=30.0, status="a_pagar", due_date="2099-06-10"
    )
    r = await client.patch(
        f"/financeiro/despesas/{d['id']}",
        headers=auth_headers,
        json={"mark_paid": True, "paid_method": "dinheiro"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pago" and r.json()["method"] == "dinheiro"

    atual = (await client.get("/caixa/atual", headers=auth_headers)).json()
    assert atual["balance"]["by_type"]["despesa"] == 30.0
    assert atual["balance"]["expected_cash"] == 170.0


@pytest.mark.asyncio
async def test_mark_paid_dinheiro_sem_caixa_com_enforcement_409(client, auth_headers):
    await _set_enforced(True)
    d = await _criar(client, auth_headers, amount=50.0, status="a_pagar", due_date="2099-06-10")
    r = await client.patch(
        f"/financeiro/despesas/{d['id']}",
        headers=auth_headers,
        json={"mark_paid": True, "paid_method": "dinheiro"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "cash_register_closed"


@pytest.mark.asyncio
async def test_unmark_paid_compensa_o_caixa(client, auth_headers):
    await _abrir_caixa(client, auth_headers, "0.00")
    d = await _criar(client, auth_headers, amount=40.0, method="dinheiro", status="pago")

    atual = (await client.get("/caixa/atual", headers=auth_headers)).json()
    assert atual["balance"]["expected_cash"] == -40.0

    r = await client.patch(
        f"/financeiro/despesas/{d['id']}", headers=auth_headers, json={"mark_paid": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "a_pagar"

    atual = (await client.get("/caixa/atual", headers=auth_headers)).json()
    assert atual["balance"]["adjustments"] == 40.0
    assert atual["balance"]["expected_cash"] == 0.0


@pytest.mark.asyncio
async def test_patch_amount_bloqueado_se_ja_no_caixa(client, auth_headers):
    await _abrir_caixa(client, auth_headers, "0.00")
    d = await _criar(client, auth_headers, amount=25.0, method="dinheiro", status="pago")
    r = await client.patch(
        f"/financeiro/despesas/{d['id']}", headers=auth_headers, json={"amount": 99.0}
    )
    assert r.status_code == 409


# ─── recorrências (CRUD) ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recorrencia_crud(client, auth_headers):
    desc = _tag()
    r = await client.post(
        "/financeiro/despesas/recorrencias",
        headers=auth_headers,
        json={
            "description": desc,
            "category": _tag(),
            "amount": 500.0,
            "day_of_month": 10,
            "method": "debito_automatico",
            "subgroup": "fixa",
        },
    )
    assert r.status_code == 201, r.text
    rec_id = r.json()["id"]
    assert r.json()["active"] is True

    r = await client.get("/financeiro/despesas/recorrencias", headers=auth_headers)
    assert any(x["id"] == rec_id for x in r.json())

    r = await client.patch(
        f"/financeiro/despesas/recorrencias/{rec_id}",
        headers=auth_headers,
        json={"amount": 550.0, "active": False},
    )
    assert r.status_code == 200
    assert r.json()["amount"] == 550.0 and r.json()["active"] is False

    r = await client.patch(
        "/financeiro/despesas/recorrencias/99999999",
        headers=auth_headers,
        json={"amount": 1.0},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_recorrencia_dia_invalido_422(client, auth_headers):
    r = await client.post(
        "/financeiro/despesas/recorrencias",
        headers=auth_headers,
        json={"description": _tag(), "category": _tag(), "amount": 10.0, "day_of_month": 31},
    )
    assert r.status_code == 422


# ─── cron interno: materialização idempotente ──────────────────────────────


@pytest.mark.asyncio
async def test_internal_run_materializa_idempotente(client, auth_headers):
    bot = _bot_headers()
    desc = _tag()
    r = await client.post(
        "/financeiro/despesas/recorrencias",
        headers=auth_headers,
        json={"description": desc, "category": _tag(), "amount": 500.0, "day_of_month": 10},
    )
    assert r.status_code == 201, r.text

    r1 = await client.post("/internal/expenses/run", headers=bot)
    assert r1.status_code == 200, r1.text
    assert r1.json()["created"] >= 1

    r2 = await client.post("/internal/expenses/run", headers=bot)
    assert r2.status_code == 200
    assert r2.json()["created"] == 0 and r2.json()["skipped"] >= 1

    # a conta nasce em "a pagar" (sem month → todas as abertas)
    r = await client.get(
        "/financeiro/despesas", headers=auth_headers, params={"status": "a_pagar"}
    )
    assert any(e["note"] is None and e["status"] == "a_pagar" for e in r.json())


@pytest.mark.asyncio
async def test_internal_run_sem_token_401(client):
    r = await client.post("/internal/expenses/run", headers={"X-Bot-Token": "errado"})
    assert r.status_code == 401


# ─── RBAC / RLS ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rbac_barbeiro_e_recepcao_403(client, barber_headers, reception_headers):
    for h in (barber_headers, reception_headers):
        assert (await client.get("/financeiro/despesas", headers=h)).status_code == 403
        r = await client.post(
            "/financeiro/despesas",
            headers=h,
            json={"category": _tag(), "amount": 10.0, "month": FUTURE_MONTH},
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_rls_isola_despesas_entre_orgs(client, auth_headers):
    d = await _criar(client, auth_headers, month=FUTURE_MONTH)
    other_org = SEED_ORG_ID + 999_000
    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org)
        rows = (
            await session.execute(select(Expense).where(Expense.id == d["id"]))
        ).scalars().all()
        assert rows == []
