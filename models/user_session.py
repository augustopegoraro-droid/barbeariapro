"""Sessões/dispositivos de login (D-68, Fase 3 — sessão, dispositivos e refresh token).

Uma linha por login/dispositivo. `refresh_token_hash` é o segredo corrente (rotativo);
`prev_refresh_token_hash` guarda o hash anterior só para detectar REUSO na janela
seguinte a uma rotação (indício de token roubado) — ver `app/api/auth.py::refresh`.

Nome `UserSession` (não `Session`) para não colidir com `sqlalchemy.ext.asyncio.AsyncSession`,
usado como `db: AsyncSession` em quase todo endpoint do projeto.
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


class UserSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_user_revoked", "user_id", "revoked_at"),
        Index("idx_sessions_refresh_hash", "refresh_token_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    prev_refresh_token_hash: Mapped[Optional[str]] = mapped_column(Text)
    jti_current: Mapped[str] = mapped_column(Text, nullable=False)
    device_label: Mapped[Optional[str]] = mapped_column(Text)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    os: Mapped[Optional[str]] = mapped_column(Text)
    browser: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(Text)
    # Reservado para geolocalização por IP (fora do MVP — precisaria de base
    # MaxMind GeoLite2 com licença/atualização própria). Não preenchido hoje.
    ip_geo: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    refresh_expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    revoked_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
