"""Avaliação pós-atendimento pelo cliente final (Fase A do app nativo).

Cobre as regras do endpoint `POST /public/{sub}/me/appointments/{id}/rating`:
só atendimento concluído, dentro da janela, uma única vez (append-only), só o
da própria sessão (D-79) e isolamento RLS entre organizações.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from models import Appointment, AppointmentRating, AppointmentStatus
from tests.conftest import SEED_ORG_ID

from tests.test_public_site import (  # noqa: F401
    BASE,
    _create_session,
    _first_slot,
    public_seed,
)

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_ratings():
    yield
    # `appointment_ratings` nasce sem GRANT DELETE ao `barber_app` (de
    # propósito: avaliação é definitiva) — limpar exige a role dona.
    if ADMIN_URL:
        eng = create_engine(ADMIN_URL)
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM appointment_ratings"))
        eng.dispose()


async def _book(client, seed) -> str:
    slots = await _first_slot(client, seed)
    resp = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": seed["service_id"],
            "barber_id": seed["barber_id"],
            "start_at": slots[0],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["public_id"]


async def _force_status(
    public_id: str, status: AppointmentStatus, *, end_at: datetime | None = None
) -> int:
    """Coloca o agendamento no estado que o teste precisa (o site não conclui)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            appt = (
                await s.execute(
                    select(Appointment).where(Appointment.public_id == public_id)
                )
            ).scalar_one()
            appt.status = status
            if end_at is not None:
                appt.start_at = end_at - timedelta(minutes=30)
                appt.end_at = end_at
            return appt.id


@pytest.mark.asyncio
async def test_avaliar_agendado_422(client, public_seed):
    await _create_session(client)
    public_id = await _book(client, public_seed)
    resp = await client.post(
        f"{BASE}/me/appointments/{public_id}/rating", json={"rating": 5}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_avaliar_concluido_201_e_duplicata_409(client, public_seed):
    await _create_session(client)
    public_id = await _book(client, public_seed)
    appt_id = await _force_status(
        public_id, AppointmentStatus.concluido, end_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )

    resp = await client.post(
        f"{BASE}/me/appointments/{public_id}/rating",
        json={"rating": 5, "comment": "  Atendimento impecável  "},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["rating"] == 5
    assert resp.json()["comment"] == "Atendimento impecável"

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        row = (
            await s.execute(
                select(AppointmentRating).where(AppointmentRating.appointment_id == appt_id)
            )
        ).scalar_one()
        assert row.barber_id == public_seed["barber_id"]
        assert row.organization_id == SEED_ORG_ID

    # segunda avaliação do mesmo atendimento → 409 (é definitiva)
    dup = await client.post(
        f"{BASE}/me/appointments/{public_id}/rating", json={"rating": 1}
    )
    assert dup.status_code == 409, dup.text

    # e a listagem passa a refletir rating/can_rate
    mine = await client.get(f"{BASE}/me/appointments")
    entry = next(a for a in mine.json() if a["public_id"] == public_id)
    assert entry["rating"] == 5
    assert entry["can_rate"] is False
    assert entry["service_id"] == public_seed["service_id"]
    assert entry["barber_id"] == public_seed["barber_id"]


@pytest.mark.asyncio
async def test_can_rate_true_quando_concluido_sem_avaliacao(client, public_seed):
    await _create_session(client)
    public_id = await _book(client, public_seed)
    await _force_status(
        public_id, AppointmentStatus.concluido, end_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )
    mine = await client.get(f"{BASE}/me/appointments")
    entry = next(a for a in mine.json() if a["public_id"] == public_id)
    assert entry["can_rate"] is True
    assert entry["rating"] is None


@pytest.mark.asyncio
async def test_avaliar_fora_da_janela_422(client, public_seed):
    await _create_session(client)
    public_id = await _book(client, public_seed)
    stale = datetime.now(timezone.utc) - timedelta(
        days=settings.public_rating_window_days + 5
    )
    await _force_status(public_id, AppointmentStatus.concluido, end_at=stale)

    resp = await client.post(
        f"{BASE}/me/appointments/{public_id}/rating", json={"rating": 4}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_avaliar_de_outra_sessao_404(client, public_seed):
    _, phone = await _create_session(client)
    public_id = await _book(client, public_seed)
    await _force_status(
        public_id, AppointmentStatus.concluido, end_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )

    client.cookies.clear()
    await _create_session(client, phone=phone)  # mesmo telefone, outro aparelho
    resp = await client.post(
        f"{BASE}/me/appointments/{public_id}/rating", json={"rating": 5}
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("valor", [0, 6, -1])
async def test_rating_fora_de_1_a_5_422(client, public_seed, valor):
    await _create_session(client)
    public_id = await _book(client, public_seed)
    await _force_status(
        public_id, AppointmentStatus.concluido, end_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    resp = await client.post(
        f"{BASE}/me/appointments/{public_id}/rating", json={"rating": valor}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_rls_isola_avaliacao_entre_orgs(client, public_seed):
    """Sessão escopada em outra org não enxerga a avaliação da org semeada."""
    await _create_session(client)
    public_id = await _book(client, public_seed)
    appt_id = await _force_status(
        public_id, AppointmentStatus.concluido, end_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    resp = await client.post(
        f"{BASE}/me/appointments/{public_id}/rating", json={"rating": 3}
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID + 99999)
        found = (
            await s.execute(
                select(AppointmentRating).where(AppointmentRating.appointment_id == appt_id)
            )
        ).scalars().all()
        assert found == []
