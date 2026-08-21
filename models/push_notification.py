"""Notificações push (Web Push/VAPID) — profissionais e clientes finais.

`PushSubscription`: uma subscrição de navegador por dispositivo, ligada a
`user_id` (equipe, D-68) OU `client_id` (cliente final, D-79) — nunca os
dois. Nunca se apaga de verdade: `revoked_at` marca subscrição morta
(404/410 do push service) ou desativada pelo próprio usuário.

`PushNotificationLog`: molde de `MessageLog`, mas genérico para os dois
tipos de assinante. Idempotência atômica por `idempotency_key` (mesmo padrão
de `app/services/reminders.py`), independente do canal WhatsApp.
`user_id`/`client_id` sem FK de propósito (molde 0048/`audit_logs.
actor_user_id`) — fato histórico, não trava se o registro for removido.
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
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .enums import DeliveryStatus, PushChannel, PushSubscriberType, pg_enum


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "(subscriber_type = 'user' AND user_id IS NOT NULL AND client_id IS NULL) OR "
            "(subscriber_type = 'client' AND client_id IS NOT NULL AND user_id IS NULL)",
            name="push_subscriptions_subscriber_exclusive",
        ),
        CheckConstraint(
            "(channel = 'webpush' AND p256dh IS NOT NULL AND auth_key IS NOT NULL) OR "
            "(channel = 'fcm' AND p256dh IS NULL AND auth_key IS NULL)",
            name="push_subscriptions_channel_keys",
        ),
        UniqueConstraint("endpoint", name="push_subscriptions_endpoint_uq"),
        Index("idx_push_subscriptions_org_user", "organization_id", "user_id"),
        Index("idx_push_subscriptions_org_client", "organization_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subscriber_type: Mapped[PushSubscriberType] = mapped_column(
        pg_enum(PushSubscriberType, "push_subscriber_type"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE")
    )
    # Web Push: URL do push service. FCM: "fcm:<device_token>" (migration 0060)
    # — mantém o upsert/revogação por `endpoint` valendo nos dois canais.
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[PushChannel] = mapped_column(
        pg_enum(PushChannel, "push_channel"), nullable=False, server_default="webpush"
    )
    # Chaves do protocolo Web Push — não existem no FCM (CHECK amarra ao canal).
    p256dh: Mapped[Optional[str]] = mapped_column(Text)
    auth_key: Mapped[Optional[str]] = mapped_column(Text)
    device_platform: Mapped[Optional[str]] = mapped_column(Text)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))


class PushNotificationLog(Base):
    __tablename__ = "push_notification_log"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="push_notification_log_idempotency_uq"),
        Index("idx_push_notification_log_org_created", "organization_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subscriber_type: Mapped[PushSubscriberType] = mapped_column(
        pg_enum(PushSubscriberType, "push_subscriber_type"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    appointment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        pg_enum(DeliveryStatus, "delivery_status"),
        nullable=False,
        server_default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
