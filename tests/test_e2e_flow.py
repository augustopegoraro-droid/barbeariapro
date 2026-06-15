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
