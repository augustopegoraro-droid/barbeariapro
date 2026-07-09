"""audit_logs com hash-chain + retenção configurável (Fase 4)

Revision ID: 0039_audit_logs
Revises: 0038_sessions_hardening
Create Date: 2026-07-09

Cria o núcleo de auditoria (ARQUITETURA_ALVO.md §1.7): tabela `audit_logs`
por tenant, com `prev_hash`/`hash` encadeados (detecta adulteração) e
`organizations.audit_retention_months` (default 12) para a política de
retenção configurável por org.

Append-only de fato: `barber_app` recebe só SELECT/INSERT (sem UPDATE/DELETE
direto) — mesmo espírito do `platform_audit_log` (0034), mas COM RLS (é dado
do tenant, lido pelo próprio gestor da org, ao contrário do audit de
plataforma). A purga por retenção roda por função SECURITY DEFINER
(`app_audit_purge_expired`), chamada pelo cron interno
(`POST /internal/audit/purge`, X-Bot-Token) — molde `app_platform_active_org_ids`
(billing) para operações administrativas que não passam pelo role da app.

RLS com FORCE explícito (a tabela nasce depois do loop dinâmico de 0038 —
não é coberta por ele, precisa forçar aqui mesmo, conforme o próprio 0038
já avisa na docstring).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0039_audit_logs"
down_revision = "0038_sessions_hardening"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "audit_retention_months",
            sa.Integer,
            nullable=False,
            server_default=sa.text("12"),
        ),
    )
    op.execute(
        "ALTER TABLE organizations ADD CONSTRAINT organizations_audit_retention_positive "
        "CHECK (audit_retention_months > 0)"
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_kind", sa.Text, nullable=False, server_default=sa.text("'user'")),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=True),
        sa.Column("resource_id", sa.Text, nullable=True),
        sa.Column("before", JSONB, nullable=True),
        sa.Column("after", JSONB, nullable=True),
        sa.Column("result", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("prev_hash", sa.Text, nullable=True),
        sa.Column("hash", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'bot', 'system')", name="audit_logs_actor_kind_valid"
        ),
        sa.CheckConstraint(
            "result IN ('allow', 'deny')", name="audit_logs_result_valid"
        ),
    )
    op.create_index("idx_audit_logs_org_created", "audit_logs", ["organization_id", "created_at"])
    op.create_index("idx_audit_logs_org_actor", "audit_logs", ["organization_id", "actor_user_id"])
    op.create_index(
        "idx_audit_logs_org_resource", "audit_logs", ["organization_id", "resource_type", "resource_id"]
    )
    op.create_index("idx_audit_logs_org_action", "audit_logs", ["organization_id", "action"])

    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON audit_logs "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    # Append-only: sem UPDATE/DELETE para o role da app — só SELECT/INSERT.
    op.execute("GRANT SELECT, INSERT ON audit_logs TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_audit_purge_expired()
        RETURNS bigint
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH deleted AS (
                DELETE FROM audit_logs a
                USING organizations o
                WHERE a.organization_id = o.id
                  AND a.created_at < now() - (o.audit_retention_months || ' months')::interval
                RETURNING a.id
            )
            SELECT count(*) FROM deleted
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION app_audit_purge_expired() TO barber_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_audit_purge_expired()")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_logs")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")
    op.drop_table("audit_logs")
    op.execute(
        "ALTER TABLE organizations DROP CONSTRAINT IF EXISTS organizations_audit_retention_positive"
    )
    op.drop_column("organizations", "audit_retention_months")
