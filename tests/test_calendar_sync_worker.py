"""Testes unitários do worker de sync Calendar (app/services/calendar_sync.py).

Sem rede real: mock do google_calendar client.
Sem banco de produção: usa o banco de staging via fixtures do conftest.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.services.calendar_sync import push_appointment, _build_event
from models.enums import IntegrationProvider, IntegrationStatus, SyncStatus
from models.integration import CalendarSync, IntegrationAccount


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_encryption_key", key)
    from app.core import crypto
    crypto._fernet_for.cache_clear()
    yield key
    crypto._fernet_for.cache_clear()


# ─── _build_event (unitário, sem DB) ──────────────────────────────────────────

def _make_appt(service_name="Corte", client_name="João", barber_name="Taylor"):
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock

    item = MagicMock()
    item.position = 1
    item.service.name = service_name
    item.barber.name = barber_name

    appt = MagicMock()
    appt.client.name = client_name
    appt.items = [item]
    now = datetime(2026, 6, 21, 14, 0, 0, tzinfo=timezone.utc)
    appt.start_at = now
    appt.end_at = now + timedelta(minutes=30)
    return appt


def test_build_event_summary_e_barber():
    appt = _make_appt(service_name="Barba", client_name="Carlos", barber_name="Pablo")
    ev = _build_event(appt)
    assert ev["summary"] == "Barba — Carlos"
    assert "Pablo" in ev["description"]
    assert "dateTime" in ev["start"]
    assert "dateTime" in ev["end"]


def test_build_event_sem_items():
    appt = _make_appt()
    appt.items = []
    ev = _build_event(appt)
    assert "Atendimento" in ev["summary"]


# ─── push_appointment: no-op sem IntegrationAccount ──────────────────────────

@pytest.mark.asyncio
async def test_push_noop_sem_integration_account(client, auth_headers):
    """push_appointment é no-op se a org não tem Calendar conectado."""
    seed_org = int(os.environ.get("SEED_ORG_ID", "1"))
    with patch("app.services.google_calendar.insert_event") as mock_insert:
        await push_appointment(appointment_id=9999, org_id=seed_org, action="upsert")
    mock_insert.assert_not_called()


# ─── push_appointment: fluxo upsert (insert) ──────────────────────────────────

@pytest.mark.asyncio
async def test_push_upsert_cria_evento_e_grava_sync(client, auth_headers, monkeypatch):
    """Com IntegrationAccount ativa, push cria o evento e grava calendar_sync."""
    from app.db.session import AsyncSessionLocal, set_current_org

    seed_org = int(os.environ.get("SEED_ORG_ID", "1"))

    # Busca um agendamento real do banco de staging
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            from models import Appointment
            appt = (
                await session.execute(
                    select(Appointment)
                    .where(Appointment.organization_id == seed_org)
                    .limit(1)
                )
            ).scalar_one_or_none()

    if appt is None:
        pytest.skip("Nenhum agendamento no banco de staging para testar")

    appt_id = appt.id

    # Cria uma IntegrationAccount temporária para a org
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            acc = IntegrationAccount(
                organization_id=seed_org,
                provider=IntegrationProvider.google_calendar,
                token_encrypted=encrypt_token("at-worker-test"),
                refresh_token_encrypted=encrypt_token("rt-worker-test"),
                status=IntegrationStatus.active,
            )
            session.add(acc)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            acc = (
                await session.execute(
                    select(IntegrationAccount)
                    .where(
                        IntegrationAccount.organization_id == seed_org,
                        IntegrationAccount.provider == IntegrationProvider.google_calendar,
                    )
                    .order_by(IntegrationAccount.id.desc())
                    .limit(1)
                )
            ).scalar_one()
            acc_id = acc.id

    mock_result = {"id": "evt-worker-1", "etag": '"etag-w1"', "status": "confirmed"}

    with patch("app.services.google_calendar.insert_event", new_callable=AsyncMock, return_value=mock_result):
        await push_appointment(appt_id, seed_org, "upsert")

    # Verifica que calendar_sync foi gravado
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            sync_row = (
                await session.execute(
                    select(CalendarSync).where(
                        CalendarSync.appointment_id == appt_id,
                        CalendarSync.integration_account_id == acc_id,
                    )
                )
            ).scalar_one_or_none()

    assert sync_row is not None
    assert sync_row.external_event_id == "evt-worker-1"
    assert sync_row.sync_status == SyncStatus.synced

    # Limpa
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            await session.delete(
                await session.get(CalendarSync, sync_row.id)
            )
            await session.delete(
                await session.get(IntegrationAccount, acc_id)
            )


# ─── push_appointment: falha da API → status failed ──────────────────────────

@pytest.mark.asyncio
async def test_push_falha_api_grava_failed(monkeypatch):
    """Erro da API Google → sync_status=failed, sem propagar exceção."""
    from app.db.session import AsyncSessionLocal, set_current_org
    from app.services.google_calendar import GoogleCalendarError

    seed_org = int(os.environ.get("SEED_ORG_ID", "1"))

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            from models import Appointment
            appt = (
                await session.execute(
                    select(Appointment)
                    .where(Appointment.organization_id == seed_org)
                    .limit(1)
                )
            ).scalar_one_or_none()

    if appt is None:
        pytest.skip("Nenhum agendamento no banco de staging")

    appt_id = appt.id

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            acc = IntegrationAccount(
                organization_id=seed_org,
                provider=IntegrationProvider.google_calendar,
                token_encrypted=encrypt_token("at-fail-test"),
                status=IntegrationStatus.active,
            )
            session.add(acc)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            acc_id = (
                await session.execute(
                    select(IntegrationAccount.id)
                    .where(
                        IntegrationAccount.organization_id == seed_org,
                        IntegrationAccount.provider == IntegrationProvider.google_calendar,
                    )
                    .order_by(IntegrationAccount.id.desc())
                    .limit(1)
                )
            ).scalar_one()

    async def boom(*a, **kw):
        raise GoogleCalendarError("403 forbidden")

    with patch("app.services.google_calendar.insert_event", side_effect=boom):
        await push_appointment(appt_id, seed_org, "upsert")  # não deve propagar

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            sync_row = (
                await session.execute(
                    select(CalendarSync).where(
                        CalendarSync.appointment_id == appt_id,
                        CalendarSync.integration_account_id == acc_id,
                    )
                )
            ).scalar_one_or_none()

    assert sync_row is not None
    assert sync_row.sync_status == SyncStatus.failed

    # Limpa
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_current_org(session, seed_org)
            await session.delete(await session.get(CalendarSync, sync_row.id))
            await session.delete(await session.get(IntegrationAccount, acc_id))
