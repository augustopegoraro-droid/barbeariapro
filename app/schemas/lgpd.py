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
    # Versão da política aceita — sem ela o histórico prova que houve aceite,
    # mas não a que texto (D-86).
    policy_version: Optional[str] = None
    created_at: datetime


class AnonymizeClientOut(BaseModel):
    client_id: int
    anonymized_at: datetime
