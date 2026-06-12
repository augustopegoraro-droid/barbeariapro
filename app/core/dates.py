# file: app/core/dates.py
"""Helpers de data no fuso local da aplicação.

Agregações "por dia" (dashboard, financeiro, agenda) devem usar o dia local
(settings.app_timezone), não o dia UTC — um atendimento às 21h em Palmas
pertence ao dia local em que aconteceu, não ao dia seguinte em UTC.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings


def local_tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def today_local() -> date:
    return datetime.now(local_tz()).date()


def local_date(col: ColumnElement) -> ColumnElement:
    """Expressão SQL: data local (app_timezone) de um TIMESTAMPTZ."""
    return cast(func.timezone(settings.app_timezone, col), Date)
