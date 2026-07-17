"""Site público do cliente final (D-79): tenant por subdomínio, vitrine,
slots, sessão sem OTP, agendamento, isolamento entre sessões e cancelamento.

Roda contra o DB semeado (scripts/seed.py) como o resto da suíte; o
subdomínio de teste é gravado na org semeada pelo fixture (idempotente).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.db.session import AsyncSessionLocal, set_current_org
from models import (
    Appointment,
    BarberService,
    BusinessHours,
    Client,
    ClientSession,
    ClientVisibilitySettings,
    Organization,
    Service,
    Unit,
)
from tests.conftest import SEED_ORG_ID

SUBDOMAIN = "testpub"
BASE = f"/public/{SUBDOMAIN}"


def _test_phone() -> str:
    """Telefone E.164 único por chamada (faixa fictícia +5563999xxxxxx)."""
    return "+5563999" + str(uuid.uuid4().int)[:6]


async def _clear_info_cache() -> None:
    try:
        from app.db.redis import get_redis

        await get_redis().delete(f"public_info:{SEED_ORG_ID}")
    except Exception:
        pass


@pytest_asyncio.fixture
async def public_seed():
    """Garante subdomínio na org semeada + devolve um serviço/barbeiro
    vinculados; limpa os artefatos criados pelos testes ao final."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            org = (
                await s.execute(select(Organization).where(Organization.id == SEED_ORG_ID))
            ).scalar_one_or_none()
            if org is None:
                pytest.skip("DB semeado indisponível.")
            org.subdomain = SUBDOMAIN

            link = (
                await s.execute(
                    select(BarberService)
                    .join(Service, Service.id == BarberService.service_id)
                    .where(Service.is_active.is_(True))
                    .where(Service.deleted_at.is_(None))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if link is None:
                pytest.skip("Seed sem vínculo barbeiro↔serviço.")
            svc = (
                await s.execute(select(Service).where(Service.id == link.service_id))
            ).scalar_one()
            unit = (
                await s.execute(
                    select(Unit)
                    .where(Unit.organization_id == SEED_ORG_ID)
                    .where(Unit.deleted_at.is_(None))
                    .order_by(Unit.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if unit is None:
                pytest.skip("Seed sem unidade.")
            weekdays = (
                (
                    await s.execute(
                        select(BusinessHours.weekday).where(BusinessHours.unit_id == unit.id)
                    )
                )
                .scalars()
                .all()
            )
            if not weekdays:
                pytest.skip("Seed sem business_hours.")

    await _clear_info_cache()
    data = {
        "service_id": link.service_id,
        "barber_id": link.barber_id,
        "duration": svc.default_duration_min,
        "weekdays": set(weekdays),
        "unit_id": unit.id,
    }
    yield data

    # Limpeza via role admin: o `barber_app` não tem DELETE em client_sessions
    # (por desenho — sessão se revoga, não se apaga). Sem ADMIN_DATABASE_URL,
    # pula a limpeza (staging de teste tolera resíduo).
    admin_url = os.environ.get("ADMIN_DATABASE_URL")
    if admin_url:
        from sqlalchemy.ext.asyncio import create_async_engine

        eng = create_async_engine(admin_url)
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM appointment_items WHERE appointment_id IN "
                    "(SELECT id FROM appointments WHERE created_by_client_session_id IS NOT NULL)"
                )
            )
            await conn.execute(
                text("DELETE FROM appointments WHERE created_by_client_session_id IS NOT NULL")
            )
            await conn.execute(text("DELETE FROM client_sessions"))
            await conn.execute(text("DELETE FROM clients WHERE phone_e164 LIKE '+5563999%'"))
            await conn.execute(
                text("DELETE FROM client_visibility_settings WHERE organization_id = :o"),
                {"o": SEED_ORG_ID},
            )
        await eng.dispose()
    await _clear_info_cache()


def _next_open_day(weekdays: set[int]) -> datetime:
    """Próximo dia (a partir de amanhã) com expediente (weekday 0=domingo)."""
    day = datetime.now(timezone.utc) + timedelta(days=1)
    for _ in range(8):
        if (day.weekday() + 1) % 7 in weekdays:
            return day
        day += timedelta(days=1)
    pytest.skip("Nenhum dia com expediente na próxima semana.")


async def _create_session(client, name="Cliente Teste", phone=None):
    phone = phone or _test_phone()
    resp = await client.post(f"{BASE}/auth/session", json={"name": name, "phone": phone})
    assert resp.status_code == 201, resp.text
    return resp, phone


async def _first_slot(client, seed):
    day = _next_open_day(seed["weekdays"])
    resp = await client.get(
        f"{BASE}/slots",
        params={
            "service_id": seed["service_id"],
            "barber_id": seed["barber_id"],
            "day": day.date().isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    slots = resp.json()["slots"]
    if not slots:
        pytest.skip("Sem slot livre no dia de teste (agenda cheia).")
    return slots


# ─── tenant / vitrine ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subdominio_inexistente_404(client, public_seed):
    resp = await client.get("/public/nao-existe-xyz/info")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_info_vitrine(client, public_seed):
    resp = await client.get(f"{BASE}/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"]
    assert body["services"], "vitrine sem serviços"
    svc = next(s for s in body["services"] if s["id"] == public_seed["service_id"])
    assert public_seed["barber_id"] in svc["barber_ids"]
    assert body["professionals"]
    assert body["hours"], "show_hours default deveria expor horários"


@pytest.mark.asyncio
async def test_info_respeita_visibilidade_custom(client, public_seed):
    """mode=custom com ids vazios esconde profissionais → nenhum serviço agendável."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            s.add(
                ClientVisibilitySettings(
                    organization_id=SEED_ORG_ID,
                    services={"mode": "all", "ids": []},
                    professionals={"mode": "custom", "ids": []},
                    show_hours=False,
                    banner={},
                    public_info={},
                )
            )
    await _clear_info_cache()
    resp = await client.get(f"{BASE}/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["professionals"] == []
    assert body["services"] == []
    assert body["hours"] == []
    # e o slots/booking também respeitam (profissional oculto → 404)
    day = _next_open_day(public_seed["weekdays"])
    resp = await client.get(
        f"{BASE}/slots",
        params={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "day": day.date().isoformat(),
        },
    )
    assert resp.status_code == 404


# ─── sessão ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_criar_sessao_novo_e_merge(client, public_seed):
    resp, phone = await _create_session(client, name="Fulano Site")
    assert resp.json()["is_new_client"] is True
    assert "tt_session" in resp.cookies

    # mesmo telefone de novo → merge (não duplica), nome original preservado
    resp2, _ = await _create_session(client, name="Outro Nome", phone=phone)
    assert resp2.json()["is_new_client"] is False
    assert resp2.json()["client_name"] == "Fulano Site"

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            count = (
                await s.execute(select(Client).where(Client.phone_e164 == phone))
            ).scalars().all()
            assert len(count) == 1


@pytest.mark.asyncio
async def test_telefone_invalido_422(client, public_seed):
    resp = await client.post(f"{BASE}/auth/session", json={"name": "X Y", "phone": "abc"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cliente_bloqueado_403(client, public_seed):
    phone = _test_phone()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            s.add(
                Client(
                    organization_id=SEED_ORG_ID,
                    name="Bloqueado",
                    phone_e164=phone,
                    is_blocked=True,
                )
            )
    resp = await client.post(f"{BASE}/auth/session", json={"name": "Bloqueado", "phone": phone})
    assert resp.status_code == 403


# ─── slots + agendamento ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agendar_sem_sessao_401(client, public_seed):
    slots = await _first_slot(client, public_seed)
    resp = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": slots[0],
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_fluxo_agendamento_completo(client, public_seed):
    await _create_session(client)
    slots = await _first_slot(client, public_seed)
    chosen = slots[0]

    resp = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": chosen,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "agendado"
    assert body["cancelable"] is True

    # o slot escolhido some da grade
    slots_after = await _first_slot(client, public_seed)
    assert chosen not in slots_after

    # aparece em "meus agendamentos"
    mine = await client.get(f"{BASE}/me/appointments")
    assert mine.status_code == 200
    assert any(a["public_id"] == body["public_id"] for a in mine.json())


@pytest.mark.asyncio
async def test_slot_ocupado_409(client, public_seed):
    await _create_session(client)
    slots = await _first_slot(client, public_seed)
    chosen = slots[0]
    r1 = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": chosen,
        },
    )
    assert r1.status_code == 201
    # outra sessão tenta o mesmo horário
    client.cookies.clear()
    await _create_session(client)
    r2 = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": chosen,
        },
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_isolamento_entre_sessoes_mesmo_telefone(client, public_seed):
    """Sem OTP, sessão B (mesmo telefone) NÃO vê agendamento da sessão A."""
    _, phone = await _create_session(client)
    slots = await _first_slot(client, public_seed)
    r = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": slots[0],
        },
    )
    assert r.status_code == 201

    client.cookies.clear()
    await _create_session(client, phone=phone)  # mesmo telefone, outro aparelho
    mine_b = await client.get(f"{BASE}/me/appointments")
    assert mine_b.status_code == 200
    assert mine_b.json() == []


# ─── cancelamento ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancelar_agendamento(client, public_seed):
    await _create_session(client)
    slots = await _first_slot(client, public_seed)
    r = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": slots[0],
        },
    )
    public_id = r.json()["public_id"]

    resp = await client.post(f"{BASE}/me/appointments/{public_id}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelado"

    # cancelar de novo → 422 (não está mais 'agendado')
    resp2 = await client.post(f"{BASE}/me/appointments/{public_id}/cancel")
    assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_cancelar_em_cima_da_hora_422(client, public_seed):
    await _create_session(client)
    slots = await _first_slot(client, public_seed)
    r = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": slots[0],
        },
    )
    public_id = r.json()["public_id"]

    # move o agendamento para daqui a 1h (dentro da janela mínima de 2h)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await set_current_org(s, SEED_ORG_ID)
            appt = (
                await s.execute(
                    select(Appointment).where(Appointment.public_id == uuid.UUID(public_id))
                )
            ).scalar_one()
            appt.start_at = datetime.now(timezone.utc) + timedelta(hours=1)
            appt.end_at = appt.start_at + timedelta(minutes=30)

    resp = await client.post(f"{BASE}/me/appointments/{public_id}/cancel")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_logout_revoga_sessao(client, public_seed):
    await _create_session(client)
    assert (await client.get(f"{BASE}/me/appointments")).status_code == 200
    resp = await client.post(f"{BASE}/auth/logout")
    assert resp.status_code == 204
    # o cookie antigo não vale mais mesmo se reapresentado
    assert (await client.get(f"{BASE}/me/appointments")).status_code == 401
