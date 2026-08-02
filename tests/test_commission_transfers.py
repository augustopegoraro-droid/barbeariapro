"""Repasse de comissão entre barbeiros (D-88).

Cobre a camada de cálculo (`management.py::commission_transfer_deltas` /
`commissions_by_barber`) e as rotas `POST/GET/DELETE /financeiro/.../repasse*`.
Usa datas em 2099 para isolar do seed/demais testes (molde
`test_financeiro_dre_pagamentos.py`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.session import AsyncSessionLocal, set_current_org
from app.services.management import commission_transfer_deltas, commissions_by_barber
from tests.conftest import SEED_ORG_ID
from models import (
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    Barber,
    Client,
    CommissionTransfer,
    Service,
    Unit,
)

_MONTH_FROM = date(2099, 6, 1)
_MONTH_TO = date(2099, 6, 30)
_START_AT = datetime(2099, 6, 15, 14, 0, tzinfo=timezone.utc)
_END_AT = datetime(2099, 6, 15, 14, 30, tzinfo=timezone.utc)
_CLEANUP_FROM = datetime(2099, 1, 1, tzinfo=timezone.utc)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        item_ids = (
            await session.execute(
                select(AppointmentItem.id)
                .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
                .where(Appointment.start_at >= _CLEANUP_FROM)
            )
        ).scalars().all()
        if item_ids:
            await session.execute(
                delete(CommissionTransfer).where(
                    CommissionTransfer.appointment_item_id.in_(item_ids)
                )
            )
        await session.execute(delete(Appointment).where(Appointment.start_at >= _CLEANUP_FROM))
        await session.execute(delete(Barber).where(Barber.name.like("Repasse Teste%")))
        await session.execute(delete(Client).where(Client.name.like("Cliente Repasse%")))
        await session.commit()


async def _seed_item(session, *, price="100.00", from_pct="0.50", to_pct="0.40"):
    """Cria barbeiro A (dono), barbeiro B (destino), cliente e um item
    concluído de A no período de teste. Retorna (barber_a, barber_b, item)."""
    unit = (await session.execute(select(Unit).limit(1))).scalar_one()
    service = (await session.execute(select(Service).limit(1))).scalar_one()

    suf = uuid.uuid4().int % 1_000_000
    barber_a = Barber(
        organization_id=SEED_ORG_ID, name=f"Repasse Teste A {suf}",
        commission_pct=Decimal(from_pct),
    )
    barber_b = Barber(
        organization_id=SEED_ORG_ID, name=f"Repasse Teste B {suf}",
        commission_pct=Decimal(to_pct),
    )
    client = Client(
        organization_id=SEED_ORG_ID, name=f"Cliente Repasse {suf}",
        phone_e164=f"+5563{suf:08d}"[:15],
    )
    session.add_all([barber_a, barber_b, client])
    await session.flush()

    appt = Appointment(
        organization_id=SEED_ORG_ID,
        unit_id=unit.id,
        client_id=client.id,
        display_number=500_000 + (suf % 400_000),
        start_at=_START_AT,
        end_at=_END_AT,
        status=AppointmentStatus.concluido,
        total_amount=Decimal(price),
    )
    session.add(appt)
    await session.flush()

    item = AppointmentItem(
        organization_id=SEED_ORG_ID,
        appointment_id=appt.id,
        service_id=service.id,
        barber_id=barber_a.id,
        price_charged=Decimal(price),
        duration_minutes=30,
    )
    session.add(item)
    await session.flush()
    return barber_a, barber_b, item


# ─── management.py: cálculo ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commissions_by_barber_liquido_soma_zero():
    """A soma dos deltas de repasse é sempre zero: redistribui, não cria nem
    some comissão."""
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        barber_a, barber_b, item = await _seed_item(session, price="100.00", from_pct="0.50")
        base_commission = (Decimal("100.00") * Decimal("0.50")).quantize(Decimal("0.01"))
        transferred = (base_commission * Decimal("0.30")).quantize(Decimal("0.01"))
        session.add(
            CommissionTransfer(
                organization_id=SEED_ORG_ID,
                appointment_item_id=item.id,
                from_barber_id=barber_a.id,
                to_barber_id=barber_b.id,
                pct=Decimal("0.30"),
                amount=transferred,
            )
        )
        await session.commit()
        # `set_current_org` é `SET LOCAL` (escopo de transação) — o commit
        # anterior encerrou a transação em que foi setado; a query abaixo abre
        # uma nova e precisa do tenant de novo.
        await set_current_org(session, SEED_ORG_ID)

        deltas = await commission_transfer_deltas(session, _MONTH_FROM, _MONTH_TO)
        assert deltas[barber_a.id] == -transferred
        assert deltas[barber_b.id] == transferred
        assert sum(deltas.values()) == 0

        rows = await commissions_by_barber(session, _MONTH_FROM, _MONTH_TO)
        by_id = {r["barber_id"]: r for r in rows}
        assert by_id[barber_a.id]["commission"] == base_commission - transferred
        assert by_id[barber_a.id]["revenue"] == Decimal("100.00")
        # B não tem receita própria no período, só recebeu repasse.
        assert by_id[barber_b.id]["commission"] == transferred
        assert by_id[barber_b.id]["revenue"] == Decimal("0")
        assert by_id[barber_b.id]["appointment_count"] == 0


# ─── API: criar/listar/estornar ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_criar_repasse_ok_reflete_no_financeiro_mensal(client, auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        barber_a, barber_b, item = await _seed_item(session, price="100.00", from_pct="0.50")
        item_id, from_id, to_id = item.id, barber_a.id, barber_b.id
        await session.commit()

    resp = await client.post(
        f"/financeiro/appointment-items/{item_id}/repasse-comissao",
        headers=auth_headers,
        json={"to_barber_id": to_id, "pct": 0.3, "reason": "atendimento a 4 mãos"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["from_barber_id"] == from_id
    assert body["to_barber_id"] == to_id
    assert body["amount"] == 15.0  # 100 * 0.50 * 0.30

    mensal = await client.get("/financeiro/mensal?month=2099-06", headers=auth_headers)
    assert mensal.status_code == 200, mensal.text
    by_barber = {b["barber_id"]: b for b in mensal.json()["by_barber"]}
    assert by_barber[from_id]["commission"] == 35.0  # 50 - 15
    assert by_barber[to_id]["commission"] == 15.0
    assert by_barber[to_id]["revenue"] == 0.0


@pytest.mark.asyncio
async def test_criar_repasse_mesmo_barbeiro_422(client, auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        barber_a, _barber_b, item = await _seed_item(session)
        item_id, from_id = item.id, barber_a.id
        await session.commit()

    resp = await client.post(
        f"/financeiro/appointment-items/{item_id}/repasse-comissao",
        headers=auth_headers,
        json={"to_barber_id": from_id, "pct": 0.3},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_criar_repasse_item_nao_concluido_422(client, auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        unit = (await session.execute(select(Unit).limit(1))).scalar_one()
        service = (await session.execute(select(Service).limit(1))).scalar_one()
        suf = uuid.uuid4().int % 1_000_000
        barber_a = Barber(
            organization_id=SEED_ORG_ID, name=f"Repasse Teste A {suf}",
            commission_pct=Decimal("0.5"),
        )
        barber_b = Barber(
            organization_id=SEED_ORG_ID, name=f"Repasse Teste B {suf}",
            commission_pct=Decimal("0.4"),
        )
        cliente = Client(
            organization_id=SEED_ORG_ID, name=f"Cliente Repasse {suf}",
            phone_e164=f"+5563{suf:08d}"[:15],
        )
        session.add_all([barber_a, barber_b, cliente])
        await session.flush()
        appt = Appointment(
            organization_id=SEED_ORG_ID, unit_id=unit.id, client_id=cliente.id,
            display_number=500_000 + (suf % 400_000),
            start_at=_START_AT, end_at=_END_AT,
            status=AppointmentStatus.agendado, total_amount=Decimal("100.00"),
        )
        session.add(appt)
        await session.flush()
        item = AppointmentItem(
            organization_id=SEED_ORG_ID, appointment_id=appt.id, service_id=service.id,
            barber_id=barber_a.id, price_charged=Decimal("100.00"), duration_minutes=30,
        )
        session.add(item)
        await session.flush()
        item_id, to_id = item.id, barber_b.id
        await session.commit()

    resp = await client.post(
        f"/financeiro/appointment-items/{item_id}/repasse-comissao",
        headers=auth_headers,
        json={"to_barber_id": to_id, "pct": 0.3},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_criar_repasse_reception_403(client, auth_headers, reception_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        barber_a, barber_b, item = await _seed_item(session)
        item_id, to_id = item.id, barber_b.id
        await session.commit()

    resp = await client.post(
        f"/financeiro/appointment-items/{item_id}/repasse-comissao",
        headers=reception_headers,
        json={"to_barber_id": to_id, "pct": 0.3},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_listar_e_estornar_repasse(client, auth_headers):
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        barber_a, barber_b, item = await _seed_item(session)
        item_id, to_id = item.id, barber_b.id
        await session.commit()

    created = await client.post(
        f"/financeiro/appointment-items/{item_id}/repasse-comissao",
        headers=auth_headers,
        json={"to_barber_id": to_id, "pct": 0.3},
    )
    assert created.status_code == 201, created.text
    transfer_id = created.json()["id"]

    listed = await client.get("/financeiro/repasses?month=2099-06", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert any(t["id"] == transfer_id for t in listed.json())

    deleted = await client.delete(f"/financeiro/repasses/{transfer_id}", headers=auth_headers)
    assert deleted.status_code == 204

    listed_after = await client.get("/financeiro/repasses?month=2099-06", headers=auth_headers)
    assert all(t["id"] != transfer_id for t in listed_after.json())

    # estornado: a comissão de A volta ao valor cheio (sem repasse).
    mensal = await client.get("/financeiro/mensal?month=2099-06", headers=auth_headers)
    by_barber = {b["barber_id"]: b for b in mensal.json()["by_barber"]}
    assert by_barber[barber_a.id]["commission"] == 50.0
