"""Sessão de longa duração do CLIENTE FINAL no site público (D-79).

Domínio de identidade separado de `sessions`/`UserSession` (staff, D-68):
o cliente não tem senha nem RBAC — a sessão nasce de nome+telefone (v1 sem
OTP; WhatsApp restrito, D-41) e vive por até 400 dias num cookie HttpOnly.

`verified_at` fica NULL até existir o fluxo OTP (Cloud API). Enquanto a
sessão não é verificada, ela só enxerga os agendamentos que ela mesma criou
(`appointments.created_by_client_session_id`) — nunca o histórico completo
do telefone, para que ninguém veja dados de terceiros digitando o telefone
alheio.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Text,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ClientSession(Base):
    __tablename__ = "client_sessions"
    __table_args__ = (
        Index("idx_client_sessions_token_hash", "token_hash", unique=True),
        Index("idx_client_sessions_org_client", "organization_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    device_label: Mapped[Optional[str]] = mapped_column(Text)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
