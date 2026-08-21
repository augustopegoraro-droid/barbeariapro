"""Feed de novidades/promoções (mural do gestor, lido no site público).

Arquivar é `deleted_at` — a tabela nasce sem GRANT de DELETE ao `barber_app`
(migration 0061), mesmo padrão de `services`/`barbers`.

`public_id` (uuid) é o identificador exposto na vitrine pública; o id
sequencial fica só no painel.
"""

from __future__ import annotations

import uuid as uuid_pkg
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    TIMESTAMP,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FeedPost(Base):
    __tablename__ = "feed_posts"
    __table_args__ = (
        CheckConstraint(
            "char_length(title) BETWEEN 2 AND 120", name="feed_posts_title_len"
        ),
        CheckConstraint("char_length(body) <= 2000", name="feed_posts_body_len"),
        Index(
            "idx_feed_posts_org_published",
            "organization_id",
            "is_published",
            text("published_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    public_id: Mapped[uuid_pkg.UUID] = mapped_column(
        Uuid, nullable=False, unique=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    image_path: Mapped[Optional[str]] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    published_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
