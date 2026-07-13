# file: app/schemas/lgpd.py
"""Contratos dos direitos do titular (Fase 8, `/admin/security/lgpd`)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ConsentRecordOut(BaseModel):
    channel: str
    status: str
    source: Optional[str] = None
    created_at: datetime


class AnonymizeClientOut(BaseModel):
    client_id: int
    anonymized_at: datetime
