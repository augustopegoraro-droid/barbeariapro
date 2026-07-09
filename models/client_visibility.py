"""Visibilidade do site público do cliente final (Fase 6, ARQUITETURA_ALVO.md §1.9).

1:1 por org — o site público em si ainda não existe (Fase 0 da auditoria);
esta tabela guarda só a CONFIGURAÇÃO que o gestor define, pronta para quando
o site consumir (endpoint público de leitura fica para quando o produto
tiver a página em si).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, TIMESTAMP, Boolean, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ClientVisibilitySettings(Base):
    __tablename__ = "client_visibility_settings"

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    services: Mapped[dict] = mapped_column(JSONB, nullable=False)
    professionals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    show_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    show_reviews: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    show_promotions: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    banner: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_info: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
