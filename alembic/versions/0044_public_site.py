"""site público do cliente final (D-79): client_sessions + canal 'site'

Revision ID: 0044_public_site
Revises: 0043_rls_hardening_v17_v18
Create Date: 2026-07-17

Infra de dados do site público de agendamento (ARQUITETURA_SITE_PUBLICO.md):

1. `client_sessions` — sessão de longa duração do CLIENTE FINAL (domínio de
   identidade separado de `sessions`/staff, D-68): token opaco de 256 bits,
   só o hash persiste. v1 sem OTP (WhatsApp restrito, D-41): `verified_at`
   nasce NULL e só será preenchido quando o fluxo OTP existir (Cloud API);
   até lá a sessão enxerga apenas os agendamentos que ela mesma criou.
2. `appointments.created_by_client_session_id` — delimita o "meus
   agendamentos" da sessão não verificada (nunca o histórico do telefone).
3. `contact_channel` ganha o valor `'site'` — agendamentos nascidos no site
   são rastreáveis por canal (relatórios site × recepção × bot).

Molde RLS: 0042 (`_TENANT_ONLY`, ENABLE+FORCE, GRANT ao `barber_app`).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0044_public_site"
down_revision = "0043_rls_hardening_v17_v18"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    # PG >= 12 aceita ADD VALUE em transação, desde que o valor novo não seja
    # usado na mesma transação (não é: nenhum INSERT aqui usa 'site').
    op.execute("ALTER TYPE contact_channel ADD VALUE IF NOT EXISTS 'site'")

    op.create_table(
        "client_sessions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("device_label", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_client_sessions_token_hash", "client_sessions", ["token_hash"], unique=True
    )
    op.create_index(
        "idx_client_sessions_org_client", "client_sessions", ["organization_id", "client_id"]
    )

    op.execute("ALTER TABLE client_sessions ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON client_sessions "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE client_sessions FORCE ROW LEVEL SECURITY")
    # UPDATE: last_seen_at (sliding) + revoked_at (logout/revogação).
    op.execute("GRANT SELECT, INSERT, UPDATE ON client_sessions TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")

    op.add_column(
        "appointments",
        sa.Column(
            "created_by_client_session_id",
            sa.BigInteger,
            sa.ForeignKey("client_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_appt_client_session", "appointments", ["created_by_client_session_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_appt_client_session", table_name="appointments")
    op.drop_column("appointments", "created_by_client_session_id")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON client_sessions")
    op.execute("ALTER TABLE client_sessions DISABLE ROW LEVEL SECURITY")
    op.drop_table("client_sessions")
    # Valor de enum não é removido (PG não suporta DROP VALUE; inofensivo).
