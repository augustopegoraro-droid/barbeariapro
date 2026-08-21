"""Segundo canal de push: FCM nativo ao lado do Web Push (Fase A do app nativo).

O app nativo (Capacitor) roda dentro de um WebView — Web Push não existe lá,
o push nativo é FCM (Android e, via APNs, iOS). Em vez de uma tabela nova, a
`push_subscriptions` (0056) ganha um discriminador de canal: a subscrição FCM
usa `endpoint = "fcm:<device_token>"`, então `dispatch()`, o upsert por
`endpoint` e a revogação continuam exatamente iguais.

`p256dh`/`auth_key` são chaves de criptografia do protocolo Web Push — não
existem no FCM. Passam a nullable, com CHECK amarrando a presença ao canal
(nunca uma linha `webpush` sem chave, nunca uma `fcm` com chave).

Revision ID: 0060_push_native_channel
Revises: 0059_client_photo
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0060_push_native_channel"
down_revision = "0059_client_photo"
branch_labels = None
depends_on = None

_CHANNELS = ("webpush", "fcm")

_CHANNEL_KEYS_CHECK = (
    "(channel = 'webpush' AND p256dh IS NOT NULL AND auth_key IS NOT NULL) OR "
    "(channel = 'fcm' AND p256dh IS NULL AND auth_key IS NULL)"
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_CHANNELS, name="push_channel").create(bind, checkfirst=False)

    op.add_column(
        "push_subscriptions",
        sa.Column(
            "channel",
            postgresql.ENUM(*_CHANNELS, name="push_channel", create_type=False),
            nullable=False,
            server_default="webpush",
        ),
    )
    op.add_column(
        "push_subscriptions", sa.Column("device_platform", sa.Text(), nullable=True)
    )
    op.alter_column("push_subscriptions", "p256dh", existing_type=sa.Text(), nullable=True)
    op.alter_column("push_subscriptions", "auth_key", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        "push_subscriptions_channel_keys", "push_subscriptions", _CHANNEL_KEYS_CHECK
    )


def downgrade() -> None:
    op.drop_constraint(
        "push_subscriptions_channel_keys", "push_subscriptions", type_="check"
    )
    # Linhas FCM não têm as chaves do Web Push: some com elas antes de voltar
    # as colunas para NOT NULL (senão o downgrade falha com dado real).
    op.execute("DELETE FROM push_subscriptions WHERE channel = 'fcm'")
    op.drop_column("push_subscriptions", "device_platform")
    op.drop_column("push_subscriptions", "channel")
    op.alter_column("push_subscriptions", "p256dh", existing_type=sa.Text(), nullable=False)
    op.alter_column("push_subscriptions", "auth_key", existing_type=sa.Text(), nullable=False)
    op.execute("DROP TYPE push_channel")
