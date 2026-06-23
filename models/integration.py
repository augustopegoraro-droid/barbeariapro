"""Andaime de integrações: IntegrationAccount, CalendarSync, MessageLog."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (
    DeliveryStatus,
    IntegrationProvider,
    IntegrationStatus,
    MessageDirection,
    SyncStatus,
    pg_enum,
)

if TYPE_CHECKING:
    from .appointment import Appointment
    from .client import Client
    from .organization import Organization
    from .unit import Unit


class IntegrationAccount(Base):
    __tablename__ = "integration_accounts"
    __table_args__ = (
        Index("idx_integration_accounts_org", "organization_id"),
        Index("idx_integration_accounts_provider", "organization_id", "provider"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="CASCADE")
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        pg_enum(IntegrationProvider, "integration_provider"), nullable=False
    )
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_encrypted: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    status: Mapped[IntegrationStatus] = mapped_column(
        pg_enum(IntegrationStatus, "integration_status"),
        nullable=False,
        server_default=text("'active'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(
        back_populates="integration_accounts"
    )
    unit: Mapped[Optional["Unit"]] = relationship(
        back_populates="integration_accounts"
    )
    calendar_syncs: Mapped[List["CalendarSync"]] = relationship(
        back_populates="integration_account"
    )


class CalendarSync(Base):
    __tablename__ = "calendar_sync"
    __table_args__ = (
        UniqueConstraint(
            "appointment_id", "integration_account_id", name="calendar_sync_unique"
        ),
        CheckConstraint("attempt_count >= 0", name="calendar_sync_attempts_nonneg"),
        Index(
            "idx_calendar_sync_pending",
            "sync_status",
            postgresql_where=text("sync_status IN ('pending', 'failed')"),
        ),
        Index(
            "idx_calendar_sync_event",
            "external_event_id",
            postgresql_where=text("external_event_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
    )
    integration_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("integration_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_event_id: Mapped[Optional[str]] = mapped_column(Text)
    external_etag: Mapped[Optional[str]] = mapped_column(Text)
    sync_status: Mapped[SyncStatus] = mapped_column(
        pg_enum(SyncStatus, "sync_status"),
        nullable=False,
        server_default=text("'pending'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    appointment: Mapped["Appointment"] = relationship(back_populates="calendar_syncs")
    integration_account: Mapped["IntegrationAccount"] = relationship(
        back_populates="calendar_syncs"
    )


class MessageLog(Base):
    __tablename__ = "message_log"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="message_log_attempts_nonneg"),
        Index("idx_message_log_org_created", "organization_id", "created_at"),
        Index("idx_message_log_client", "client_id"),
        Index(
            "idx_message_log_retry",
            "next_retry_at",
            postgresql_where=text(
                "delivery_status IN ('pending', 'failed') "
                "AND next_retry_at IS NOT NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    appointment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="SET NULL")
    )
    direction: Mapped[MessageDirection] = mapped_column(
        pg_enum(MessageDirection, "message_direction"), nullable=False
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    template: Mapped[Optional[str]] = mapped_column(Text)
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        pg_enum(DeliveryStatus, "delivery_status"),
        nullable=False,
        server_default=text("'pending'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="messages")
    client: Mapped["Client"] = relationship(back_populates="messages")
    appointment: Mapped[Optional["Appointment"]] = relationship(
        back_populates="messages"
    )
