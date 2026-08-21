"""Avaliação pós-atendimento pelo cliente final (Fase A do app nativo).

Uma avaliação por atendimento (UNIQUE em `appointment_id`) e **definitiva**:
não há rota de edição/remoção e a tabela nasce sem GRANT de UPDATE/DELETE ao
`barber_app` (migration 0058) — mesmo molde append-only de `audit_logs`.

`barber_id` é denormalizado (ON DELETE SET NULL) para médias por profissional
sem join com `appointment_items`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AppointmentRating(Base):
    __tablename__ = "appointment_ratings"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="appointment_ratings_rating_range"),
        CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 1000",
            name="appointment_ratings_comment_len",
        ),
        UniqueConstraint("appointment_id", name="appointment_ratings_appointment_uq"),
        Index("idx_appointment_ratings_org_barber", "organization_id", "barber_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    appointment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    barber_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="SET NULL")
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
