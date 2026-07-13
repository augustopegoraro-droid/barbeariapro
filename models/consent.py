"""Histórico de consentimento — LGPD (Fase 8, ARQUITETURA_ALVO.md §1.11).

Append-only: evolui `ClientConsent` (D-51, estado atual por canal) sem
substituí-la — este é o log completo de cada mudança, para prova de
consentimento/opt-out numa auditoria real.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('client', 'lead', 'user')", name="consent_records_subject_type_valid"
        ),
        Index("idx_consent_records_org_subject", "organization_id", "subject_type", "subject_id"),
        Index("idx_consent_records_org_created", "organization_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
