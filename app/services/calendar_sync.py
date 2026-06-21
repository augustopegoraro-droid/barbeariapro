# file: app/services/calendar_sync.py
"""Worker de sincronização Appointment → Google Calendar (Fase 2).

Ponto de entrada: `push_appointment(appointment_id, org_id, action)`.

- No-op se a org não tiver IntegrationAccount ativa para google_calendar.
- Silencia exceções após log: falha de sync não pode derrubar o fluxo principal.
- Renova access_token automaticamente via refresh_token quando o Google retorna 401.
- Persiste resultado (external_event_id, sync_status) em calendar_sync com upsert.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.crypto import TokenCryptoError, decrypt_token, encrypt_token
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import google_calendar as gc
from models import Appointment, AppointmentItem
from models.enums import IntegrationProvider, IntegrationStatus, SyncStatus
from models.integration import CalendarSync, IntegrationAccount

_log = logging.getLogger(__name__)


def _build_event(appt: Appointment) -> dict:
    """Monta o payload do evento Google Calendar a partir do agendamento."""
    primary = min(appt.items, key=lambda i: i.position, default=None)
    client_name = appt.client.name if appt.client else "—"
    service_name = primary.service.name if primary and primary.service else "Atendimento"
    barber_name = primary.barber.name if primary and primary.barber else "—"

    tz = settings.app_timezone
    return {
        "summary": f"{service_name} — {client_name}",
        "description": f"Barbeiro: {barber_name}",
        "start": {"dateTime": appt.start_at.isoformat(), "timeZone": tz},
        "end": {"dateTime": appt.end_at.isoformat(), "timeZone": tz},
    }


async def _get_fresh_token(
    account: IntegrationAccount,
    session: AsyncSession,
) -> str:
    """Devolve access_token válido. Se expirado, tenta refresh e persiste o novo."""
    try:
        return decrypt_token(account.token_encrypted)
    except TokenCryptoError as exc:
        raise RuntimeError(f"token cifrado inválido: {exc}") from exc


async def _refresh_and_persist(
    account: IntegrationAccount,
    session: AsyncSession,
) -> str:
    """Troca o refresh_token por um novo access_token e persiste no banco."""
    if not account.refresh_token_encrypted:
        raise RuntimeError("sem refresh_token — usuário precisa reautorizar o Calendar")

    refresh_tok = decrypt_token(account.refresh_token_encrypted)
    tokens = await gc.refresh_access_token(refresh_tok)
    new_access = tokens.get("access_token")
    if not new_access:
        raise RuntimeError("refresh_token não retornou access_token")

    account.token_encrypted = encrypt_token(new_access)
    if tokens.get("refresh_token"):
        account.refresh_token_encrypted = encrypt_token(tokens["refresh_token"])
    return new_access


async def _upsert_sync_row(
    session: AsyncSession,
    appointment_id: int,
    account_id: int,
    *,
    external_event_id: Optional[str],
    external_etag: Optional[str],
    status: SyncStatus,
    attempt_delta: int = 1,
) -> None:
    stmt = (
        pg_insert(CalendarSync)
        .values(
            appointment_id=appointment_id,
            integration_account_id=account_id,
            external_event_id=external_event_id,
            external_etag=external_etag,
            sync_status=status,
            attempt_count=attempt_delta,
            last_synced_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            constraint="calendar_sync_unique",
            set_={
                "external_event_id": external_event_id,
                "external_etag": external_etag,
                "sync_status": status,
                "attempt_count": CalendarSync.attempt_count + attempt_delta,
                "last_synced_at": datetime.now(timezone.utc),
            },
        )
    )
    await session.execute(stmt)


async def push_appointment(
    appointment_id: int,
    org_id: int,
    action: Literal["upsert", "delete"],
) -> None:
    """Sincroniza um agendamento com o Google Calendar da org em background.

    Chamado como BackgroundTask após criação, reagendamento ou cancelamento.
    """
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await set_current_org(session, org_id)
                await _run_sync(session, appointment_id, org_id, action)
    except Exception:
        _log.exception(
            "calendar_sync: erro não tratado [appt=%s org=%s action=%s]",
            appointment_id, org_id, action,
        )


async def _run_sync(
    session: AsyncSession,
    appointment_id: int,
    org_id: int,
    action: Literal["upsert", "delete"],
) -> None:
    # 1. Busca IntegrationAccount ativa
    account = (
        await session.execute(
            select(IntegrationAccount)
            .where(
                IntegrationAccount.organization_id == org_id,
                IntegrationAccount.provider == IntegrationProvider.google_calendar,
                IntegrationAccount.status == IntegrationStatus.active,
            )
            .order_by(IntegrationAccount.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if account is None:
        return  # org sem Calendar conectado — no-op silencioso

    # 2. Busca registro de sync anterior (para saber event_id existente)
    existing_sync = (
        await session.execute(
            select(CalendarSync).where(
                CalendarSync.appointment_id == appointment_id,
                CalendarSync.integration_account_id == account.id,
            )
        )
    ).scalar_one_or_none()

    external_event_id = existing_sync.external_event_id if existing_sync else None

    # 3. Carrega o agendamento com relacionamentos necessários para o evento
    appt = (
        await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.client),
                selectinload(Appointment.items)
                .selectinload(AppointmentItem.service),
                selectinload(Appointment.items)
                .selectinload(AppointmentItem.barber),
            )
        )
    ).scalar_one_or_none()

    if appt is None:
        _log.warning("calendar_sync: agendamento %s não encontrado", appointment_id)
        return

    calendar_id = "primary"
    access_token = await _get_fresh_token(account, session)

    # 4. Executa a operação — com uma tentativa de refresh em caso de 401
    for attempt in range(2):
        try:
            if action == "delete" and external_event_id:
                await gc.delete_event(access_token, calendar_id, external_event_id)
                await _upsert_sync_row(
                    session, appointment_id, account.id,
                    external_event_id=None, external_etag=None,
                    status=SyncStatus.synced,
                )
                return

            if action == "upsert":
                event_payload = _build_event(appt)
                if external_event_id:
                    result = await gc.update_event(
                        access_token, calendar_id, external_event_id, event_payload
                    )
                else:
                    result = await gc.insert_event(access_token, calendar_id, event_payload)

                await _upsert_sync_row(
                    session, appointment_id, account.id,
                    external_event_id=result["id"],
                    external_etag=result.get("etag"),
                    status=SyncStatus.synced,
                )
                return

            # delete sem external_event_id = já estava fora do calendar
            return

        except gc.GoogleCalendarError as exc:
            if attempt == 0 and "401" in str(exc):
                _log.info("calendar_sync: access_token expirado, renovando [appt=%s]", appointment_id)
                try:
                    access_token = await _refresh_and_persist(account, session)
                except Exception as ref_exc:
                    _log.error("calendar_sync: falha no refresh: %s", ref_exc)
                    await _upsert_sync_row(
                        session, appointment_id, account.id,
                        external_event_id=external_event_id, external_etag=None,
                        status=SyncStatus.failed,
                    )
                    return
                continue  # retry com novo token
            _log.error("calendar_sync: erro Google [appt=%s]: %s", appointment_id, exc)
            await _upsert_sync_row(
                session, appointment_id, account.id,
                external_event_id=external_event_id, external_etag=None,
                status=SyncStatus.failed,
            )
            return
