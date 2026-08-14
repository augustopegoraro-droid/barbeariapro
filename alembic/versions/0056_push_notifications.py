"""Notificações push (Web Push/VAPID) — profissionais e clientes finais.

Duas tabelas novas, molde de `sales`/0053 e `suppliers`/0054 (RLS + FORCE,
GRANT SELECT/INSERT/UPDATE ao `barber_app`, sem DELETE):

- `push_subscriptions`: uma subscrição de navegador por dispositivo, ligada a
  `user_id` (equipe, D-68) OU `client_id` (cliente final, D-79) — nunca os
  dois (CHECK). Nunca se apaga de verdade: `revoked_at` marca subscrição
  morta (404/410 do push service) ou desativada pelo próprio usuário.
- `push_notification_log`: molde de `MessageLog` (`message_log`, D-?), mas
  genérico para os dois tipos de assinante e reusando o enum `delivery_status`
  já existente. Idempotência atômica por `idempotency_key` (mesmo padrão de
  `app/services/reminders.py`), independente do canal WhatsApp — os dois
  podem falhar sem travar um ao outro.

`user_id`/`client_id` do log ficam SEM FK de propósito (mesma lógica do
D-86/migration 0048 em `audit_logs.actor_user_id`): são fato histórico de
quem foi notificado, não devem travar/zerar se o registro for removido
depois. `appointment_id` tem FK ON DELETE SET NULL, como em `message_log`.

Revision ID: 0056_push_notifications
Revises: 0055_inventory_counts
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0056_push_notifications"
down_revision = "0055_inventory_counts"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

_SUBSCRIBER_TYPES = ("user", "client")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_SUBSCRIBER_TYPES, name="push_subscriber_type").create(
        bind, checkfirst=False
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "subscriber_type",
            postgresql.ENUM(*_SUBSCRIBER_TYPES, name="push_subscriber_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "client_id", sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("p256dh", sa.Text, nullable=False),
        sa.Column("auth_key", sa.Text, nullable=False),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_used_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(subscriber_type = 'user' AND user_id IS NOT NULL AND client_id IS NULL) OR "
            "(subscriber_type = 'client' AND client_id IS NOT NULL AND user_id IS NULL)",
            name="push_subscriptions_subscriber_exclusive",
        ),
        sa.UniqueConstraint("endpoint", name="push_subscriptions_endpoint_uq"),
    )
    op.create_index(
        "idx_push_subscriptions_org_user",
        "push_subscriptions",
        ["organization_id", "user_id"],
        postgresql_where=sa.text("user_id IS NOT NULL AND revoked_at IS NULL"),
    )
    op.create_index(
        "idx_push_subscriptions_org_client",
        "push_subscriptions",
        ["organization_id", "client_id"],
        postgresql_where=sa.text("client_id IS NOT NULL AND revoked_at IS NULL"),
    )

    op.create_table(
        "push_notification_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "subscriber_type",
            postgresql.ENUM(*_SUBSCRIBER_TYPES, name="push_subscriber_type", create_type=False),
            nullable=False,
        ),
        # Sem FK de propósito — fato histórico (molde 0048/audit_logs.actor_user_id).
        sa.Column("user_id", sa.BigInteger, nullable=True),
        sa.Column("client_id", sa.BigInteger, nullable=True),
        sa.Column(
            "appointment_id", sa.BigInteger,
            sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=False),
        sa.Column(
            "delivery_status",
            postgresql.ENUM(
                *("pending", "sent", "delivered", "failed"),
                name="delivery_status", create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("idempotency_key", name="push_notification_log_idempotency_uq"),
    )
    op.create_index(
        "idx_push_notification_log_org_created",
        "push_notification_log",
        ["organization_id", "created_at"],
    )

    for table in ("push_subscriptions", "push_notification_log"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    for table in ("push_notification_log", "push_subscriptions"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(table)
    op.execute("DROP TYPE push_subscriber_type")
