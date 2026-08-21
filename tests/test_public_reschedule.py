"""Remarcação pelo cliente final (Fase A do app nativo).

O ponto central é a **atomicidade**: cancelar o antigo e criar o novo na mesma
transação. Se a criação do novo falhar (conflito de horário), o antigo tem que
continuar `agendado` — o cliente nunca pode ficar sem horário nenhum.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, set_current_org
from models import Appointment, AppointmentItem, AppointmentStatus, Service
from tests.conftest import SEED_ORG_ID

from tests.test_public_site import (  # noqa: F401
    BASE,
    _create_session,
    _first_slot,
    public_seed,
)


async def _book(client, seed, start_at: str) -> dict:
    resp = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": seed["service_id"],
            "barber_id": seed["barber_id"],
            "start_at": start_at,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _status_of(public_id: str) -> AppointmentStatus:
    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        appt = (
            await s.execute(select(Appointment).where(Appointment.public_id == public_id))
        ).scalar_one()
        return appt.status


async def _other_service(seed) -> Service | None:
    """Outro serviço do mesmo barbeiro, com duração/preço diferentes."""
    from models import BarberService

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        rows = (
            (
                await s.execute(
                    select(Service)
                    .join(BarberService, BarberService.service_id == Service.id)
                    .where(BarberService.barber_id == seed["barber_id"])
                    .where(Service.id != seed["service_id"])
                    .where(Service.is_active.is_(True))
                    .where(Service.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
    return rows[0] if rows else None


@pytest.mark.asyncio
async def test_remarcar_cria_novo_e_cancela_antigo(client, public_seed):
    await _create_session(client)
    slots = await _first_slot(client, public_seed)
    if len(slots) < 2:
        pytest.skip("Precisa de 2 slots livres no dia.")
    original = await _book(client, public_seed, slots[0])

    resp = await client.post(
        f"{BASE}/me/appointments/{original['public_id']}/reschedule",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": slots[1],
        },
    )
    assert resp.status_code == 200, resp.text
    novo = resp.json()
    assert novo["public_id"] != original["public_id"]
    assert novo["status"] == "agendado"
    assert novo["start_at"].startswith(slots[1][:16])

    assert await _status_of(original["public_id"]) == AppointmentStatus.cancelado
    assert await _status_of(novo["public_id"]) == AppointmentStatus.agendado

    # a listagem mostra os dois (histórico), o novo agendado
    mine = await client.get(f"{BASE}/me/appointments")
    by_id = {a["public_id"]: a for a in mine.json()}
    assert by_id[original["public_id"]]["status"] == "cancelado"
    assert by_id[novo["public_id"]]["cancelable"] is True


@pytest.mark.asyncio
async def test_conflito_de_horario_preserva_o_antigo(client, public_seed):
    """Se o novo horário não está livre, NADA muda — nem o antigo."""
    await _create_session(client)
    slots = await _first_slot(client, public_seed)
    # a MESMA sessão agenda dois horários; remarcar o primeiro para cima do
    # segundo tem que dar 409 e deixar o primeiro intacto.
    primeiro = await _book(client, public_seed, slots[0])
    # relê a grade: com serviço de duração > 30min, `slots[1]` ainda encosta no
    # que acabou de ser marcado — o próximo livre de verdade vem daqui.
    restantes = await _first_slot(client, public_seed)
    if not restantes:
        pytest.skip("Sem segundo slot livre no dia.")
    alvo = restantes[0]
    await _book(client, public_seed, alvo)

    resp = await client.post(
        f"{BASE}/me/appointments/{primeiro['public_id']}/reschedule",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": alvo,
        },
    )
    assert resp.status_code == 409, resp.text
    assert await _status_of(primeiro["public_id"]) == AppointmentStatus.agendado


@pytest.mark.asyncio
async def test_remarcar_em_cima_da_hora_422(client, public_seed):
    await _create_session(client)
    slots = await _first_slot(client, public_seed)
    agendamento = await _book(client, public_seed, slots[0])

    # empurra o início para dentro da janela mínima de cancelamento
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            appt = (
                await s.execute(
                    select(Appointment).where(
                        Appointment.public_id == agendamento["public_id"]
                    )
                )
            ).scalar_one()
            appt.start_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            appt.end_at = appt.start_at + timedelta(minutes=30)

    resp = await client.post(
        f"{BASE}/me/appointments/{agendamento['public_id']}/reschedule",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": slots[0],
        },
    )
    assert resp.status_code == 422, resp.text
    assert await _status_of(agendamento["public_id"]) == AppointmentStatus.agendado


@pytest.mark.asyncio
async def test_trocar_servico_recalcula_preco_e_duracao(client, public_seed):
    outro = await _other_service(public_seed)
    if outro is None:
        pytest.skip("Seed sem segundo serviço vinculado ao mesmo barbeiro.")

    await _create_session(client)
    slots = await _first_slot(client, public_seed)
    original = await _book(client, public_seed, slots[0])

    resp = await client.post(
        f"{BASE}/me/appointments/{original['public_id']}/reschedule",
        json={
            "service_id": outro.id,
            "barber_id": public_seed["barber_id"],
            "start_at": slots[0],  # mesmo horário, serviço diferente
        },
    )
    assert resp.status_code == 200, resp.text
    novo = resp.json()
    assert novo["service_id"] == outro.id
    assert novo["total_amount"] == pytest.approx(float(outro.price))

    inicio = datetime.fromisoformat(novo["start_at"])
    fim = datetime.fromisoformat(novo["end_at"])
    assert (fim - inicio) == timedelta(minutes=outro.default_duration_min)

    async with AsyncSessionLocal() as s:
        await set_current_org(s, SEED_ORG_ID)
        appt = (
            await s.execute(
                select(Appointment).where(Appointment.public_id == novo["public_id"])
            )
        ).scalar_one()
        item = (
            await s.execute(
                select(AppointmentItem).where(AppointmentItem.appointment_id == appt.id)
            )
        ).scalar_one()
        assert item.service_id == outro.id
        assert item.duration_minutes == outro.default_duration_min
        assert float(item.price_charged) == pytest.approx(float(outro.price))


@pytest.mark.asyncio
async def test_remarcar_agendamento_de_outra_sessao_404(client, public_seed):
    _, phone = await _create_session(client)
    slots = await _first_slot(client, public_seed)
    agendamento = await _book(client, public_seed, slots[0])

    client.cookies.clear()
    await _create_session(client, phone=phone)
    resp = await client.post(
        f"{BASE}/me/appointments/{agendamento['public_id']}/reschedule",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": slots[0],
        },
    )
    assert resp.status_code == 404, resp.text
