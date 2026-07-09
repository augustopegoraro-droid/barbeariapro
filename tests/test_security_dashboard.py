"""Painel de segurança (Fase 5): permissão, shape da resposta e anomalia."""

from __future__ import annotations

import os

import pytest

from app.services import audit as audit_svc
from app.services.security_dashboard import DayCount, _detect_anomaly

SEED_ORG_ID = int(os.environ.get("SEED_ORG_ID", "1"))


@pytest.mark.asyncio
async def test_dashboard_requires_permission(client, reception_headers):
    resp = await client.get("/admin/security/dashboard", headers=reception_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_allowed_for_owner_has_expected_shape(client, auth_headers):
    resp = await client.get(
        "/admin/security/dashboard", params={"days": 7}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 7
    assert len(body["series"]) == 7
    for key in (
        "logins_total", "active_users", "denied_total", "connected_devices",
        "exports_total", "permission_changes_total", "critical_actions_total",
    ):
        assert key in body["cards"]


@pytest.mark.asyncio
async def test_dashboard_reflects_recent_deny(client, barber_headers, auth_headers):
    resp = await client.get(
        "/financeiro", params={"date": "2026-07-01"}, headers=barber_headers
    )
    assert resp.status_code == 403
    await audit_svc.wait_for_pending()

    dash = await client.get(
        "/admin/security/dashboard", params={"days": 7}, headers=auth_headers
    )
    assert dash.status_code == 200
    body = dash.json()
    assert body["cards"]["denied_total"] >= 1
    assert body["top_denied_actions"], "top_denied_actions vazio após um deny recente"
    assert body["recent_denied"], "recent_denied vazio após um deny recente"


def test_detect_anomaly_flags_spike_above_baseline():
    series = [DayCount(day=f"2026-07-0{i}", logins=0, denied=1) for i in range(1, 8)]
    series.append(DayCount(day="2026-07-08", logins=0, denied=10))
    anomaly = _detect_anomaly(series)
    assert anomaly is not None
    assert anomaly["today_denied"] == 10


def test_detect_anomaly_silent_when_within_baseline():
    series = [DayCount(day=f"2026-07-0{i}", logins=0, denied=2) for i in range(1, 8)]
    series.append(DayCount(day="2026-07-08", logins=0, denied=2))
    assert _detect_anomaly(series) is None


def test_detect_anomaly_silent_below_minimum_threshold():
    # Salto proporcional grande, mas volume absoluto pequeno demais p/ alarmar.
    series = [DayCount(day=f"2026-07-0{i}", logins=0, denied=0) for i in range(1, 8)]
    series.append(DayCount(day="2026-07-08", logins=0, denied=1))
    assert _detect_anomaly(series) is None
