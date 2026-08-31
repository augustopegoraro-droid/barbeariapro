"""Caixa vivo (D-101) — abrir/fechar turno + ledger de movimentos.

Cobre: ciclo abrir/fechar; ≤1 caixa aberto por unidade; bloqueio (409
`cash_register_closed`) de recebimento em dinheiro sem caixa quando o
enforcement da org está ligado; auto-post na conclusão de atendimento em
dinheiro e na venda em dinheiro; cartão/Pix não tocam no caixa; sangria/
suprimento/ajuste e a aritmética do saldo esperado; fechamento congela
`expected_amount`/`difference`; estorno de venda cancelada; RLS entre orgs;
RBAC (recepção opera, barbeiro não vê); enforcement desligado → sem bloqueio.

`cash_movements`/`cash_sessions` são append-only para `barber_app` (sem DELETE)
— a limpeza usa `ADMIN_DATABASE_URL`, molde `tests/test_vendas.py`.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text, update

from app.db.session import AsyncSessionLocal, set_current_org
from tests.conftest import SEED_ORG_ID
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    CashSession,
    Client,
    Organization,
    Service,
    Unit,
)

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")
_CLEANUP_FROM = datetime(2099, 1, 1, tzinfo=timezone.utc)

# `cash_movements`/`cash_sessions` são append-only para `barber_app` (sem
# DELETE) — a limpeza precisa de conexão admin.
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="ADMIN_DATABASE_URL necessário para limpar tabelas append-only do caixa."
)


def _suf() -> int:
    return uuid.uuid4().int % 1_000_000


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
        d = {"o": SEED_ORG_ID, "dt": _CLEANUP_FROM}
        conn.execute(text("DELETE FROM cash_movements WHERE organization_id = :o"), d)
        conn.execute(text("DELETE FROM cash_sessions WHERE organization_id = :o"), d)
        conn.execute(
            text(
                "DELETE FROM sale_payments WHERE sale_id IN "
                "(SELECT id FROM sales WHERE created_at >= :dt "
                " OR client_id IN (SELECT id FROM clients WHERE name LIKE 'Cliente Caixa%'))"
            ),
            d,
        )
        conn.execute(
            text(
                "DELETE FROM stock_movements WHERE variant_id IN "
                "(SELECT v.id FROM product_variants v JOIN products p ON p.id = v.product_id "
                " WHERE p.name LIKE 'Produto Caixa%')"
            )
        )
        conn.execute(
            text(
                "DELETE FROM sale_items WHERE variant_id IN "
                "(SELECT v.id FROM product_variants v JOIN products p ON p.id = v.product_id "
                " WHERE p.name LIKE 'Produto Caixa%')"
            )
        )
        conn.execute(text("DELETE FROM sales WHERE client_id IN (SELECT id FROM clients WHERE name LIKE 'Cliente Caixa%')"))
        conn.execute(
            text(
                "DELETE FROM payments WHERE appointment_id IN "
                "(SELECT id FROM appointments WHERE start_at >= :dt)"
            ),
            d,
        )
        conn.execute(
            text(
                "DELETE FROM loyalty_point_ledger WHERE client_id IN "
                "(SELECT id FROM clients WHERE name LIKE 'Cliente Caixa%')"
            )
        )
        conn.execute(
            text(
                "DELETE FROM client_loyalty WHERE client_id IN "
                "(SELECT id FROM clients WHERE name LIKE 'Cliente Caixa%')"
            )
        )
        conn.execute(
            text(
                "DELETE FROM appointment_items WHERE appointment_id IN "
                "(SELECT id FROM appointments WHERE start_at >= :dt)"
            ),
            d,
        )
        conn.execute(text("DELETE FROM appointments WHERE start_at >= :dt"), d)
        conn.execute(
            text(
                "DELETE FROM product_variants WHERE product_id IN "
                "(SELECT id FROM products WHERE name LIKE 'Produto Caixa%')"
            )
        )
        conn.execute(text("DELETE FROM products WHERE name LIKE 'Produto Caixa%'"))
        conn.execute(text("DELETE FROM barbers WHERE name LIKE 'Caixa Teste%'"))
        conn.execute(text("DELETE FROM clients WHERE name LIKE 'Cliente Caixa%'"))
        conn.execute(
            text("UPDATE organizations SET cash_register_enforced = false WHERE id = :o"), d
        )
    eng.dispose()


async def _seed_appointment(*, amount: str = "50.00") -> int:
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        unit = (await session.execute(select(Unit).limit(1))).scalar_one()
        service = (await session.execute(select(Service).limit(1))).scalar_one()
        suf = _suf()
        barber = Barber(organization_id=SEED_ORG_ID, name=f"Caixa Teste {suf}", commission_pct=Decimal("0.5"))
        cliente = Client(
            organization_id=SEED_ORG_ID,
            name=f"Cliente Caixa {suf}",
            phone_e164=f"+5563{suf:08d}"[:15],
        )
        session.add_all([barber, cliente])
        await session.flush()
        appt = Appointment(
            organization_id=SEED_ORG_ID,
            unit_id=unit.id,
            client_id=cliente.id,
            display_number=910_000 + (suf % 80_000),
            start_at=datetime(2099, 8, 1, 14, 0, tzinfo=timezone.utc),
            end_at=datetime(2099, 8, 1, 14, 30, tzinfo=timezone.utc),
            status=AppointmentStatus.agendado,
            total_amount=Decimal(amount),
        )
        session.add(appt)
        await session.flush()
        session.add(
            AppointmentItem(
                organization_id=SEED_ORG_ID,
                appointment_id=appt.id,
                service_id=service.id,
                barber_id=barber.id,
                price_charged=Decimal(amount),
                duration_minutes=30,
            )
        )
        await session.flush()
        appt_id = appt.id
        await session.commit()
    return appt_id


async def _abrir(client, headers, opening: str = "100.00"):
    resp = await client.post("/caixa/abrir", headers=headers, json={"opening_float": opening})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _produto(client, headers, *, price="10.00", stock="20") -> int:
    resp = await client.post(
        "/produtos",
        headers=headers,
        json={"name": f"Produto Caixa {_suf()}", "tracks_stock": True, "variants": [{"name": "Único", "price": price}]},
    )
    assert resp.status_code == 201, resp.text
    variant_id = resp.json()["variants"][0]["id"]
    resp = await client.post(
        "/estoque/movimentacoes",
        headers=headers,
        json={"variant_id": variant_id, "movement_type": "entrada_ajuste", "qty": stock},
    )
    assert resp.status_code == 201, resp.text
    return variant_id


# ─── ciclo de vida ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_abrir_e_fechar_caixa(client, auth_headers):
    await _abrir(client, auth_headers, "100.00")

    atual = await client.get("/caixa/atual", headers=auth_headers)
    assert atual.status_code == 200
    body = atual.json()
    assert body["session"]["status"] == "aberto"
    assert body["balance"]["expected_cash"] == 100.0

    fechar = await client.post("/caixa/fechar", headers=auth_headers, json={"counted_amount": "100.00"})
    assert fechar.status_code == 200, fechar.text
    fb = fechar.json()["session"]
    assert fb["status"] == "fechado"
    assert fb["expected_amount"] == 100.0
    assert fb["difference"] == 0.0

    depois = await client.get("/caixa/atual", headers=auth_headers)
    assert depois.json()["session"] is None


@pytest.mark.asyncio
async def test_abrir_duas_vezes_409(client, auth_headers):
    await _abrir(client, auth_headers)
    resp = await client.post("/caixa/abrir", headers=auth_headers, json={"opening_float": "50.00"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_fechar_sem_caixa_409(client, auth_headers):
    resp = await client.post("/caixa/fechar", headers=auth_headers, json={"counted_amount": "0"})
    assert resp.status_code == 409


# ─── bloqueio de recebimento em dinheiro ─────────────────────────────────────


@pytest.mark.asyncio
async def test_concluir_dinheiro_sem_caixa_bloqueia(client, auth_headers):
    await _set_enforced(True)
    appt_id = await _seed_appointment(amount="50.00")
    resp = await client.patch(
        f"/barbeiro/atendimento/{appt_id}/concluir",
        headers=auth_headers,
        json={"method": "dinheiro", "amount": 50.0},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "cash_register_closed"


@pytest.mark.asyncio
async def test_concluir_cartao_sem_caixa_ok(client, auth_headers):
    await _set_enforced(True)
    appt_id = await _seed_appointment(amount="50.00")
    resp = await client.patch(
        f"/barbeiro/atendimento/{appt_id}/concluir",
        headers=auth_headers,
        json={"method": "cartao", "amount": 50.0},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_venda_dinheiro_sem_caixa_bloqueia(client, auth_headers):
    await _set_enforced(True)
    variant_id = await _produto(client, auth_headers, price="5.00")
    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={"items": [{"variant_id": variant_id, "qty": "2"}], "payments": [{"amount": "10.00", "method": "dinheiro"}]},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "cash_register_closed"


@pytest.mark.asyncio
async def test_enforcement_desligado_nao_bloqueia(client, auth_headers):
    # conftest já deixa enforced=False; sem caixa aberto a conclusão em dinheiro passa.
    appt_id = await _seed_appointment(amount="30.00")
    resp = await client.patch(
        f"/barbeiro/atendimento/{appt_id}/concluir",
        headers=auth_headers,
        json={"method": "dinheiro", "amount": 30.0},
    )
    assert resp.status_code == 200, resp.text


# ─── auto-post no caixa aberto ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concluir_dinheiro_gera_movimento(client, auth_headers):
    await _abrir(client, auth_headers, "100.00")
    appt_id = await _seed_appointment(amount="50.00")
    resp = await client.patch(
        f"/barbeiro/atendimento/{appt_id}/concluir",
        headers=auth_headers,
        json={"method": "dinheiro", "amount": 50.0, "tip_amount": 10.0},
    )
    assert resp.status_code == 200, resp.text

    atual = (await client.get("/caixa/atual", headers=auth_headers)).json()
    # 100 troco + 50 serviço + 10 gorjeta em dinheiro = 160
    assert atual["balance"]["expected_cash"] == 160.0
    assert atual["balance"]["by_type"]["venda_servico"] == 60.0

    session_id = atual["session"]["id"]
    movs = (await client.get("/caixa/movimentos", headers=auth_headers, params={"session_id": session_id})).json()
    vs = [m for m in movs if m["type"] == "venda_servico"]
    assert len(vs) == 1 and vs[0]["reference_type"] == "payment"


@pytest.mark.asyncio
async def test_concluir_cartao_nao_toca_caixa(client, auth_headers):
    await _abrir(client, auth_headers, "100.00")
    appt_id = await _seed_appointment(amount="50.00")
    resp = await client.patch(
        f"/barbeiro/atendimento/{appt_id}/concluir",
        headers=auth_headers,
        json={"method": "cartao", "amount": 50.0},
    )
    assert resp.status_code == 200, resp.text
    atual = (await client.get("/caixa/atual", headers=auth_headers)).json()
    assert atual["balance"]["expected_cash"] == 100.0
    assert atual["balance"]["by_type"]["venda_servico"] == 0.0
    assert atual["balance"]["card_total"] >= 50.0


@pytest.mark.asyncio
async def test_venda_dinheiro_gera_movimento(client, auth_headers):
    await _abrir(client, auth_headers, "0.00")
    variant_id = await _produto(client, auth_headers, price="5.00")
    resp = await client.post(
        "/vendas",
        headers=auth_headers,
        json={"items": [{"variant_id": variant_id, "qty": "3"}], "payments": [{"amount": "15.00", "method": "dinheiro"}]},
    )
    assert resp.status_code == 201, resp.text
    atual = (await client.get("/caixa/atual", headers=auth_headers)).json()
    assert atual["balance"]["by_type"]["venda_produto"] == 15.0
    assert atual["balance"]["expected_cash"] == 15.0


@pytest.mark.asyncio
async def test_cancelar_venda_estorna_no_caixa(client, auth_headers):
    await _abrir(client, auth_headers, "0.00")
    variant_id = await _produto(client, auth_headers, price="5.00")
    venda = await client.post(
        "/vendas",
        headers=auth_headers,
        json={"items": [{"variant_id": variant_id, "qty": "2"}], "payments": [{"amount": "10.00", "method": "dinheiro"}]},
    )
    sale_id = venda.json()["id"]
    cancel = await client.patch(f"/vendas/{sale_id}/cancelar", headers=auth_headers)
    assert cancel.status_code == 200, cancel.text

    atual = (await client.get("/caixa/atual", headers=auth_headers)).json()
    assert atual["balance"]["adjustments"] == -10.0
    assert atual["balance"]["expected_cash"] == 0.0


# ─── movimentos manuais ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sangria_suprimento_ajuste_saldo(client, auth_headers):
    await _abrir(client, auth_headers, "100.00")
    assert (await client.post("/caixa/movimentos", headers=auth_headers, json={"type": "suprimento", "amount": "20.00"})).status_code == 201
    assert (await client.post("/caixa/movimentos", headers=auth_headers, json={"type": "sangria", "amount": "50.00", "note": "troco banco"})).status_code == 201
    assert (await client.post("/caixa/movimentos", headers=auth_headers, json={"type": "ajuste", "amount": "-10.00", "note": "erro de troco"})).status_code == 201

    atual = (await client.get("/caixa/atual", headers=auth_headers)).json()
    # 100 + 20 - 50 - 10 = 60
    assert atual["balance"]["expected_cash"] == 60.0

    fechar = await client.post("/caixa/fechar", headers=auth_headers, json={"counted_amount": "55.00"})
    assert fechar.json()["session"]["difference"] == -5.0


@pytest.mark.asyncio
async def test_sangria_sem_motivo_422(client, auth_headers):
    await _abrir(client, auth_headers)
    resp = await client.post("/caixa/movimentos", headers=auth_headers, json={"type": "sangria", "amount": "10.00"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_movimento_automatico_via_rota_manual_422(client, auth_headers):
    await _abrir(client, auth_headers)
    resp = await client.post("/caixa/movimentos", headers=auth_headers, json={"type": "venda_servico", "amount": "10.00"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_movimento_sem_caixa_409(client, auth_headers):
    resp = await client.post("/caixa/movimentos", headers=auth_headers, json={"type": "suprimento", "amount": "10.00"})
    assert resp.status_code == 409


# ─── RBAC / RLS ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reception_opera_barbeiro_nao_ve(client, reception_headers, barber_headers):
    assert (await client.get("/caixa/atual", headers=reception_headers)).status_code == 200
    abrir = await client.post("/caixa/abrir", headers=reception_headers, json={"opening_float": "0"})
    assert abrir.status_code == 201, abrir.text
    assert (await client.get("/caixa/atual", headers=barber_headers)).status_code == 403


@pytest.mark.asyncio
async def test_rls_isola_caixa_entre_orgs(client, auth_headers):
    body = await _abrir(client, auth_headers)
    session_id = body["session"]["id"]
    other_org = SEED_ORG_ID + 999_000
    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org)
        rows = (await session.execute(select(CashSession).where(CashSession.id == session_id))).scalars().all()
        assert rows == []
