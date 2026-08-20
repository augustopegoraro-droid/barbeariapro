"""Notificações push (Web Push/VAPID) — profissionais e clientes finais.

Cobre subscrição self-service (equipe via JWT, cliente via cookie de sessão),
idempotência atômica de `app/services/push.py::dispatch` (molde de
`app/services/reminders.py`), revogação de subscrição morta (404/410) e
isolamento RLS entre organizações.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_current_org
from app.services import push as push_svc
from models import PushNotificationLog, PushSubscriberType, PushSubscription
from tests.conftest import SEED_ORG_ID

from tests.test_public_site import BASE, _create_session, _first_slot, public_seed  # noqa: F401

ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL")


def _endpoint() -> str:
    return f"https://fcm.googleapis.com/fcm/send/teste-{uuid.uuid4().hex}"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    # `push_notification_log` é append-only (sem GRANT DELETE a `barber_app`,
    # de propósito — mesmo molde de `audit_logs`/`stock_movements`); a
    # limpeza de teste precisa da role dona (molde `test_estoque.py`).
    # `push_subscriptions`/`push_notification_log` não têm GRANT DELETE a
    # `barber_app` (de propósito — subscrição nunca se apaga de verdade, só
    # revoga; log é append-only, mesmo molde de `audit_logs`/`stock_movements`).
    # Limpeza de teste precisa da role dona (molde `test_estoque.py`).
    if ADMIN_URL:
        eng = create_engine(ADMIN_URL)
        with eng.begin() as conn:
            conn.execute(
                text("DELETE FROM push_notification_log WHERE idempotency_key LIKE 'test_push_%'")
            )
            conn.execute(
                text(
                    "DELETE FROM push_notification_log WHERE kind = 'booking_confirmation' "
                    "AND organization_id = :org"
                ),
                {"org": SEED_ORG_ID},
            )
            conn.execute(
                text(
                    "DELETE FROM push_notification_log WHERE kind = 'gestor_alert' "
                    "AND organization_id = :org"
                ),
                {"org": SEED_ORG_ID},
            )
            conn.execute(text("DELETE FROM push_subscriptions WHERE endpoint LIKE '%teste-%'"))
        eng.dispose()


# ─── subscrição da equipe (JWT) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_staff_subscribe_and_unsubscribe(client, auth_headers):
    endpoint = _endpoint()
    resp = await client.post(
        "/notificacoes/push/subscription",
        headers=auth_headers,
        json={"endpoint": endpoint, "p256dh": "chave-p256dh", "auth": "chave-auth"},
    )
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        row = (
            await session.execute(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
        ).scalar_one()
        assert row.subscriber_type == PushSubscriberType.user
        assert row.client_id is None
        assert row.revoked_at is None

    resp = await client.request(
        "DELETE",
        "/notificacoes/push/subscription",
        headers=auth_headers,
        json={"endpoint": endpoint},
    )
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        row = (
            await session.execute(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
        ).scalar_one()
        assert row.revoked_at is not None


@pytest.mark.asyncio
async def test_staff_unsubscribe_inexistente_404(client, auth_headers):
    resp = await client.request(
        "DELETE",
        "/notificacoes/push/subscription",
        headers=auth_headers,
        json={"endpoint": _endpoint()},
    )
    assert resp.status_code == 404


# ─── subscrição do cliente final (cookie) + confirmação imediata ────────────


@pytest.mark.asyncio
async def test_public_subscribe_and_booking_triggers_confirmation(client, public_seed):
    await _create_session(client)
    endpoint = _endpoint()
    resp = await client.post(
        f"{BASE}/push/subscription",
        json={"endpoint": endpoint, "p256dh": "chave-p256dh", "auth": "chave-auth"},
    )
    assert resp.status_code == 204, resp.text

    slots = await _first_slot(client, public_seed)
    resp = await client.post(
        f"{BASE}/appointments",
        json={
            "service_id": public_seed["service_id"],
            "barber_id": public_seed["barber_id"],
            "start_at": slots[0],
        },
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        log_row = (
            await session.execute(
                select(PushNotificationLog)
                .where(PushNotificationLog.kind == "booking_confirmation")
                .order_by(PushNotificationLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        assert log_row is not None, "confirmação imediata deveria ter disparado o claim"


# ─── idempotência / dispatch ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_idempotency_nao_duplica():
    endpoint = _endpoint()
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        # Precisa de um user_id real (FK). Usa o primeiro usuário da org semeada.
        from models import User

        user = (
            await session.execute(select(User).where(User.organization_id == SEED_ORG_ID).limit(1))
        ).scalar_one()

        session.add(
            PushSubscription(
                organization_id=SEED_ORG_ID,
                subscriber_type=PushSubscriberType.user,
                user_id=user.id,
                endpoint=endpoint,
                p256dh="p",
                auth_key="a",
            )
        )
        await session.commit()
        # SET LOCAL não sobrevive ao commit (nova transação implícita) — reseta
        # antes de cada operação seguinte na mesma sessão (V18a).
        await set_current_org(session, SEED_ORG_ID)

        key = f"test_push_idempotency_{uuid.uuid4().hex}"
        first = await push_svc.dispatch(
            session,
            org_id=SEED_ORG_ID,
            kind="reminder_30m",
            idempotency_key=key,
            subscriber_type=PushSubscriberType.user,
            user_id=user.id,
            client_id=None,
            appointment_id=None,
            title="t",
            body="b",
        )
        await session.commit()
        await set_current_org(session, SEED_ORG_ID)
        second = await push_svc.dispatch(
            session,
            org_id=SEED_ORG_ID,
            kind="reminder_30m",
            idempotency_key=key,
            subscriber_type=PushSubscriberType.user,
            user_id=user.id,
            client_id=None,
            appointment_id=None,
            title="t",
            body="b",
        )
        await session.commit()

    assert first in ("sent", "no_target")  # sem VAPID em teste, nunca "sent" de verdade
    assert second == "skipped"

    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        rows = (
            await session.execute(
                select(PushNotificationLog).where(PushNotificationLog.idempotency_key == key)
            )
        ).scalars().all()
        assert len(rows) == 1


# ─── alertas do gestor (D-97) — Web Push além do WhatsApp ────────────────────


@pytest.mark.asyncio
async def test_alertas_gestor_dispara_push_uma_vez_por_dia(monkeypatch):
    """`gestor_notify.send_alerts` deve disparar 1 push por tipo de alerta por
    gestor por dia — a 2ª chamada no mesmo dia (molde do cron a cada 2h) não
    duplica, graças à `idempotency_key` incluindo a data."""
    from datetime import date as _date

    from app.services import gestor_notify as _notify
    from app.services import management
    from models import User

    endpoint = _endpoint()
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        owner = (
            await session.execute(
                select(User).where(User.organization_id == SEED_ORG_ID).limit(1)
            )
        ).scalar_one()
        session.add(
            PushSubscription(
                organization_id=SEED_ORG_ID,
                subscriber_type=PushSubscriberType.user,
                user_id=owner.id,
                endpoint=endpoint,
                p256dh="p",
                auth_key="a",
            )
        )
        await session.commit()
        await set_current_org(session, SEED_ORG_ID)

        fake_alerts = [{"type": "meta", "message": "teste de alerta"}]

        async def _fake_revenue_alerts(db, target_date):
            return fake_alerts

        monkeypatch.setattr(management, "revenue_alerts", _fake_revenue_alerts)

        target = _date.today()
        first = await _notify.send_alerts(session, target, org_id=SEED_ORG_ID)
        await session.commit()
        await set_current_org(session, SEED_ORG_ID)
        second = await _notify.send_alerts(session, target, org_id=SEED_ORG_ID)
        await session.commit()

    assert first["push_targets"] >= 1
    assert first["push_sent"] + first["push_skipped"] == first["push_targets"]
    # 2ª execução no mesmo dia: mesma idempotency_key → tudo "skipped" (dedup).
    assert second["push_sent"] == 0

    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        rows = (
            await session.execute(
                select(PushNotificationLog).where(
                    PushNotificationLog.kind == "gestor_alert",
                    PushNotificationLog.organization_id == SEED_ORG_ID,
                )
            )
        ).scalars().all()
        # 1 alerta × N gestores × 1 dia — a 2ª chamada não deve criar linha nova.
        assert len(rows) == first["push_targets"]


@pytest.mark.asyncio
async def test_alertas_gestor_sem_org_id_nao_dispara_push():
    """Sem `org_id` (comportamento anterior ao D-97), o push fica de fora e o
    contrato antigo do WhatsApp segue intacto — nenhum chamador existente quebra."""
    from datetime import date as _date

    from app.services import gestor_notify as _notify

    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        result = await _notify.send_alerts(session, _date.today())
    assert result["push_targets"] == 0
    assert result["push_sent"] == 0


@pytest.mark.asyncio
async def test_dispatch_sem_subscricao_e_no_target():
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        from models import User

        user = (
            await session.execute(select(User).where(User.organization_id == SEED_ORG_ID).limit(1))
        ).scalar_one()

        key = f"test_push_no_target_{uuid.uuid4().hex}"
        result = await push_svc.dispatch(
            session,
            org_id=SEED_ORG_ID,
            kind="reminder_30m",
            idempotency_key=key,
            subscriber_type=PushSubscriberType.user,
            user_id=user.id,
            client_id=None,
            appointment_id=None,
            title="t",
            body="b",
        )
        await session.commit()
    assert result == "no_target"


# ─── revogação em 404/410 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_push_revoga_subscricao_morta():
    endpoint = _endpoint()
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        from models import User

        user = (
            await session.execute(select(User).where(User.organization_id == SEED_ORG_ID).limit(1))
        ).scalar_one()

        sub = PushSubscription(
            organization_id=SEED_ORG_ID,
            subscriber_type=PushSubscriberType.user,
            user_id=user.id,
            endpoint=endpoint,
            p256dh="p",
            auth_key="a",
        )
        session.add(sub)
        await session.commit()
        await set_current_org(session, SEED_ORG_ID)
        sub_id = sub.id

        class _FakeResponse:
            status_code = 410

        class _FakeWebPushException(Exception):
            def __init__(self):
                self.response = _FakeResponse()

        with patch.object(settings, "vapid_public_key", "pub"), patch.object(
            settings, "vapid_private_key", "priv"
        ), patch("pywebpush.webpush", side_effect=_FakeWebPushException()), patch(
            "pywebpush.WebPushException", _FakeWebPushException
        ):
            ok = await push_svc.send_push(session, sub, title="t", body="b")
        await session.commit()
        await set_current_org(session, SEED_ORG_ID)
        assert ok is False

        refreshed = (
            await session.execute(select(PushSubscription).where(PushSubscription.id == sub_id))
        ).scalar_one()
        assert refreshed.revoked_at is not None


# ─── RLS ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rls_isola_subscricao_entre_orgs():
    other_org_id = SEED_ORG_ID + 999_000
    endpoint = _endpoint()
    async with AsyncSessionLocal() as session:
        await set_current_org(session, SEED_ORG_ID)
        from models import User

        user = (
            await session.execute(select(User).where(User.organization_id == SEED_ORG_ID).limit(1))
        ).scalar_one()
        session.add(
            PushSubscription(
                organization_id=SEED_ORG_ID,
                subscriber_type=PushSubscriberType.user,
                user_id=user.id,
                endpoint=endpoint,
                p256dh="p",
                auth_key="a",
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        await set_current_org(session, other_org_id)
        rows = (
            await session.execute(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
        ).scalars().all()
        assert rows == []
