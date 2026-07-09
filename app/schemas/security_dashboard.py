# file: app/schemas/security_dashboard.py
"""Contratos do painel de segurança (`/admin/security/dashboard`, Fase 5)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SecurityDashboardCards(BaseModel):
    logins_total: int
    active_users: int
    denied_total: int
    connected_devices: int
    exports_total: int
    permission_changes_total: int
    critical_actions_total: int


class SecurityDashboardDay(BaseModel):
    day: str
    logins: int
    denied: int


class TopDeniedAction(BaseModel):
    action: str
    count: int


class RecentDeniedEvent(BaseModel):
    id: int
    action: str
    actor_email: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime


class SecurityAnomaly(BaseModel):
    message: str
    today_denied: int
    baseline_avg: float


class SecurityDashboardOut(BaseModel):
    days: int
    cards: SecurityDashboardCards
    series: list[SecurityDashboardDay]
    top_denied_actions: list[TopDeniedAction]
    recent_denied: list[RecentDeniedEvent]
    anomaly: Optional[SecurityAnomaly] = None
