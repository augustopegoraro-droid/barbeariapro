"""
Teste E2E do fluxo crítico do MVP: login → criar cliente → criar agendamento.

Exercita o caminho que o frontend percorre (auth + RLS + full-access), garantindo
que não há 401/403 indevidos e que o agendamento é persistido. Limpa o agendamento
criado via conexão admin (a role do app sob RLS não tem DELETE em appointments).
"""
from __future__ import annotations

import os
import uuid

import pytest

ADMIN_DSN = os.environ.get(
    "ADMIN_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/barbeariapro",
).replace("+psycopg", "")

# Par barbeiro/serviço válido (existe em barber_services no seed da org 3).
BARBER_ID = 1
SERVICE_ID = 6
# Slot bem no futuro para não conflitar com a agenda semeada.
START_AT = "2026-12-30T14:00:00-03:00"


def _admin_cleanup_appointment(appt_id: int) -> None:
    import psycopg

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DELETE FROM appointment_items WHERE appointment_id = %s", (appt_id,))
        conn.execute("DELETE FROM appointments WHERE id = %s", (appt_id,))


@pytest.mark.asyncio
async def test_login_cria_cliente_cria_agendamento(client, auth_headers):
    # 1) cliente novo com telefone único
    suf = uuid.uuid4().int % 100000
    cc = await client.post(
        "/clientes",
        headers=auth_headers,
        json={"name": "Cliente E2E", "phone": f"6398{suf:05d}"},
    )
    assert cc.status_code == 201, cc.text
    client_id = cc.json()["id"]

    appt_id = None
    try:
        # 2) agendamento
        ac = await client.post(
            "/agenda",
            headers=auth_headers,
            json={
                "client_id": client_id,
                "barber_id": BARBER_ID,
                "service_id": SERVICE_ID,
                "start_at": START_AT,
            },
        )
        assert ac.status_code == 201, ac.text
        appt = ac.json()
        appt_id = appt["id"]
        assert appt["client_name"] == "Cliente E2E"
        assert appt["status"] == "agendado"

        # 3) aparece na agenda do dia
        listed = await client.get("/agenda?date=2026-12-30", headers=auth_headers)
        assert listed.status_code == 200
        assert any(a["id"] == appt_id for a in listed.json())
    finally:
        if appt_id is not None:
            _admin_cleanup_appointment(appt_id)
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)


async def _par_valido(client, auth_headers):
    """Descobre um par (barbeiro, serviço) realmente vinculado neste banco."""
    barbers = (await client.get("/agenda/barbers", headers=auth_headers)).json()
    for b in barbers:
        svcs = (
            await client.get(f"/agenda/services?barber_id={b['id']}", headers=auth_headers)
        ).json()
        if svcs:
            return b, svcs[0]
    return None, None


async def _servico_com_dois_barbeiros(client, auth_headers):
    """Encontra um serviço executado por >=2 profissionais (ou None)."""
    barbers = (await client.get("/agenda/barbers", headers=auth_headers)).json()
    svc_barbers: dict[int, list] = {}
    for b in barbers:
        svcs = (
            await client.get(f"/agenda/services?barber_id={b['id']}", headers=auth_headers)
        ).json()
        for s in svcs:
            svc_barbers.setdefault(s["id"], []).append(b)
    for sid, bs in svc_barbers.items():
        if len(bs) >= 2:
            return sid, bs[0], bs[1]
    return None, None, None


async def _novo_cliente_e_agendamento(client, auth_headers, *, barber_id, service_id, start_at=START_AT):
    """Cria um cliente único + agendamento. Retorna (client_id, appt_json)."""
    suf = uuid.uuid4().int % 100000
    cc = await client.post(
        "/clientes",
        headers=auth_headers,
        json={"name": "Cliente Reag", "phone": f"6397{suf:05d}"},
    )
    assert cc.status_code == 201, cc.text
    client_id = cc.json()["id"]
    ac = await client.post(
        "/agenda",
        headers=auth_headers,
        json={
            "client_id": client_id,
            "barber_id": barber_id,
            "service_id": service_id,
            "start_at": start_at,
        },
    )
    assert ac.status_code == 201, ac.text
    return client_id, ac.json()


@pytest.mark.asyncio
async def test_reagendar_troca_horario_mantendo_profissional(client, auth_headers):
    barber, svc = await _par_valido(client, auth_headers)
    if not barber:
        pytest.skip("sem par profissional↔serviço no banco")
    client_id, appt = await _novo_cliente_e_agendamento(
        client, auth_headers, barber_id=barber["id"], service_id=svc["id"]
    )
    appt_id = appt["id"]
    try:
        rr = await client.patch(
            f"/agenda/{appt_id}/reagendar",
            headers=auth_headers,
            json={"start_at": "2026-12-30T16:00:00-03:00"},
        )
        assert rr.status_code == 200, rr.text
        out = rr.json()
        assert out["barber_id"] == barber["id"]  # profissional inalterado
        assert out["start_at"].startswith("2026-12-30T19:00")  # 16:00-03 == 19:00Z
    finally:
        _admin_cleanup_appointment(appt_id)
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)


@pytest.mark.asyncio
async def test_reagendar_barbeiro_inexistente_404(client, auth_headers):
    barber, svc = await _par_valido(client, auth_headers)
    if not barber:
        pytest.skip("sem par profissional↔serviço no banco")
    client_id, appt = await _novo_cliente_e_agendamento(
        client, auth_headers, barber_id=barber["id"], service_id=svc["id"]
    )
    appt_id = appt["id"]
    try:
        rr = await client.patch(
            f"/agenda/{appt_id}/reagendar",
            headers=auth_headers,
            json={"start_at": START_AT, "barber_id": 999999},
        )
        assert rr.status_code == 404, rr.text
    finally:
        _admin_cleanup_appointment(appt_id)
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)


@pytest.mark.asyncio
async def test_reagendar_troca_de_profissional(client, auth_headers):
    sid, b1, b2 = await _servico_com_dois_barbeiros(client, auth_headers)
    if sid is None:
        pytest.skip("sem serviço executado por dois profissionais")
    client_id, appt = await _novo_cliente_e_agendamento(
        client, auth_headers, barber_id=b1["id"], service_id=sid
    )
    appt_id = appt["id"]
    try:
        rr = await client.patch(
            f"/agenda/{appt_id}/reagendar",
            headers=auth_headers,
            json={"start_at": "2026-12-30T15:00:00-03:00", "barber_id": b2["id"]},
        )
        assert rr.status_code == 200, rr.text
        out = rr.json()
        assert out["barber_id"] == b2["id"]
        assert out["barber_name"] == b2["name"]
    finally:
        _admin_cleanup_appointment(appt_id)
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)


@pytest.mark.asyncio
async def test_agendamento_barbeiro_inexistente_404(client, auth_headers):
    suf = uuid.uuid4().int % 100000
    cc = await client.post(
        "/clientes",
        headers=auth_headers,
        json={"name": "Cliente E2E 2", "phone": f"6398{suf:05d}"},
    )
    client_id = cc.json()["id"]
    try:
        ac = await client.post(
            "/agenda",
            headers=auth_headers,
            json={
                "client_id": client_id,
                "barber_id": 999999,
                "service_id": SERVICE_ID,
                "start_at": START_AT,
            },
        )
        assert ac.status_code == 404
    finally:
        await client.delete(f"/clientes/{client_id}", headers=auth_headers)
