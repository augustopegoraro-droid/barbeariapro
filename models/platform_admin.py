"""Superadmin da PLATAFORMA (dono do SaaS).

Tabela GLOBAL, conceitualmente separada de `users` (que opera UMA barbearia):
não tem `organization_id` e não está sob RLS. O acesso pela aplicação é feito
apenas via funções `SECURITY DEFINER` (migration 0021) — o role `barber_app`
não tem GRANT direto nesta tabela. Ver `app/services/platform.py`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Identity, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PlatformAdmin(Base):
    __tablename__ = "platform_admins"
    __table_args__ = (
        UniqueConstraint("email", name="platform_admins_email_unique"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
