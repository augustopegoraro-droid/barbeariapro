"""Clientes (escopo de organização) e consentimento de contato (LGPD)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import ConsentStatus, ContactChannel, pg_enum

if TYPE_CHECKING:
    from .appointment import Appointment
    from .integration import MessageLog
    from .loyalty import ClientLoyalty
    from .organization import Organization


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "phone_e164", name="clients_phone_per_org"
        ),
        CheckConstraint(
            r"phone_e164 ~ '^\+[1-9][0-9]{7,14}$'", name="clients_phone_e164_fmt"
        ),
        # idx por organization_id é coberto pelo UNIQUE acima (prefixo).
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, unique=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    acquisition_channel: Mapped[Optional[ContactChannel]] = mapped_column(
        pg_enum(ContactChannel, "contact_channel")
    )
    last_photo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_photo_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    is_blocked: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    bot_paused: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    organization: Mapped["Organization"] = relationship(back_populates="clients")
    consents: Mapped[List["ClientConsent"]] = relationship(back_populates="client")
    appointments: Mapped[List["Appointment"]] = relationship(back_populates="client")
    messages: Mapped[List["MessageLog"]] = relationship(back_populates="client")
    loyalty: Mapped[Optional["ClientLoyalty"]] = relationship(
        back_populates="client", uselist=False
    )


class ClientConsent(Base):
    __tablename__ = "client_consents"
    __table_args__ = (
        UniqueConstraint("client_id", "channel", name="client_consents_unique"),
        Index("idx_client_consents_client", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[ContactChannel] = mapped_column(
        pg_enum(ContactChannel, "contact_channel"), nullable=False
    )
    status: Mapped[ConsentStatus] = mapped_column(
        pg_enum(ConsentStatus, "consent_status"), nullable=False
    )
    source: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    client: Mapped["Client"] = relationship(back_populates="consents")
