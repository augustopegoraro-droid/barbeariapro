"""auditoria imutável da plataforma (superadmin M9/M10)

Revision ID: 0034_platform_audit_log
Revises: 0033_platform_billing_view
Create Date: 2026-07-03

Aditivo. `platform_audit_log` no molde ESTRITO de `platform_admins`: sem RLS e
SEM GRANT ao `barber_app` — escrita e leitura só via SECURITY DEFINER. Não há
função de UPDATE/DELETE (append-only de fato). CHECK espelhado no ORM (D-60).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0034_platform_audit_log"
down_revision = "0033_platform_billing_view"
branch_labels = None
depends_on = None

_FUNCTIONS = (
    "app_platform_audit_add(bigint, text, text, text, bigint, bigint, text, jsonb, text)",
    "app_platform_audit_list(int, text, bigint)",
)


def upgrade() -> None:
    op.create_table(
        "platform_audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "admin_id",
            sa.BigInteger,
            sa.ForeignKey("platform_admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("admin_email", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.BigInteger, nullable=True),
        sa.Column("organization_id", sa.BigInteger, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "category IN ('impersonation', 'subscription', 'financial', "
            "'security', 'org', 'onboarding')",
            name="platform_audit_category_valid",
        ),
    )
    op.create_index("idx_platform_audit_org", "platform_audit_log", ["organization_id"])
    op.create_index("idx_platform_audit_category", "platform_audit_log", ["category"])
    op.create_index("idx_platform_audit_created", "platform_audit_log", ["created_at"])
    # Intencional: SEM RLS e SEM GRANT (molde platform_admins).

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_audit_add(
            p_admin_id bigint, p_action text, p_category text,
            p_target_type text, p_target_id bigint, p_org_id bigint,
            p_reason text, p_metadata jsonb, p_ip text
        )
        RETURNS bigint
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            INSERT INTO platform_audit_log
                (admin_id, admin_email, action, category, target_type,
                 target_id, organization_id, reason, metadata, ip)
            SELECT pa.id, pa.email, p_action, p_category, p_target_type,
                   p_target_id, p_org_id, p_reason,
                   COALESCE(p_metadata, '{}'::jsonb), p_ip
            FROM platform_admins pa
            WHERE pa.id = p_admin_id
            RETURNING id
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_audit_list(
            p_limit int, p_category text, p_org_id bigint
        )
        RETURNS TABLE(
            id bigint, admin_email text, action text, category text,
            target_type text, target_id bigint, organization_id bigint,
            reason text, metadata jsonb, ip text, created_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT id, admin_email, action, category, target_type, target_id,
                   organization_id, reason, metadata, ip, created_at
            FROM platform_audit_log
            WHERE (p_category IS NULL OR category = p_category)
              AND (p_org_id IS NULL OR organization_id = p_org_id)
            ORDER BY created_at DESC, id DESC
            LIMIT LEAST(GREATEST(COALESCE(p_limit, 100), 1), 500)
        $$
        """
    )
    for fn in _FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO barber_app")


def downgrade() -> None:
    for fn in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.drop_index("idx_platform_audit_created", table_name="platform_audit_log")
    op.drop_index("idx_platform_audit_category", table_name="platform_audit_log")
    op.drop_index("idx_platform_audit_org", table_name="platform_audit_log")
    op.drop_table("platform_audit_log")
