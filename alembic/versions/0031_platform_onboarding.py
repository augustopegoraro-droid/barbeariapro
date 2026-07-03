"""onboarding da plataforma: sinais derivados + overrides manuais (superadmin M6)

Revision ID: 0031_platform_onboarding
Revises: 0030_platform_org_detail
Create Date: 2026-07-03

Aditivo.

- `platform_onboarding_overrides` — marcação manual de etapa (done true/false)
  vencendo a derivação automática. Molde platform_admins: sem RLS, sem GRANT;
  acesso só via SECURITY DEFINER. CHECK espelhado no ORM (D-60).

- `app_platform_onboarding_signals()` — sinais crus por org ativa numa chamada
  só (perfil preenchido, contagens, WhatsApp, financeiro, trial). A DERIVAÇÃO
  das etapas fica em Python (`app/services/onboarding_progress.py`) — regra de
  negócio versionada com o código, não no banco.

- funções de override: upsert e clear.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0031_platform_onboarding"
down_revision = "0030_platform_org_detail"
branch_labels = None
depends_on = None

_FUNCTIONS = (
    "app_platform_onboarding_signals()",
    "app_platform_onboarding_overrides()",
    "app_platform_onboarding_override_set(bigint, text, boolean, bigint)",
    "app_platform_onboarding_override_clear(bigint, text)",
)


def upgrade() -> None:
    op.create_table(
        "platform_onboarding_overrides",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage_key", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column(
            "admin_id",
            sa.BigInteger,
            sa.ForeignKey("platform_admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("admin_email", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "organization_id", "stage_key", name="platform_onboarding_org_stage_unique"
        ),
        sa.CheckConstraint(
            "length(btrim(stage_key)) > 0", name="platform_onboarding_stage_nonempty"
        ),
    )
    # Intencional (molde platform_admins): SEM RLS e SEM GRANT a barber_app.

    # ── sinais crus por org ativa (uma linha por org) ────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_onboarding_signals()
        RETURNS TABLE(
            org_id bigint, name text, created_at timestamptz,
            has_profile boolean, wa_configured boolean,
            barbers_count bigint, services_count bigint, clients_count bigint,
            appointments_count bigint, appt_30d bigint,
            payments_count bigint, expenses_count bigint,
            has_revenue_goal boolean, last_activity timestamptz,
            sub_status text, sub_period_end timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT
                o.id AS org_id, o.name, o.created_at,
                (o.legal_name IS NOT NULL OR o.cnpj IS NOT NULL
                    OR o.phone IS NOT NULL OR o.email IS NOT NULL) AS has_profile,
                (o.wa_instance_name IS NOT NULL) AS wa_configured,
                (SELECT count(*) FROM barbers b
                   WHERE b.organization_id = o.id AND b.deleted_at IS NULL) AS barbers_count,
                (SELECT count(*) FROM services s
                   WHERE s.organization_id = o.id) AS services_count,
                (SELECT count(*) FROM clients c
                   WHERE c.organization_id = o.id) AS clients_count,
                (SELECT count(*) FROM appointments a
                   WHERE a.organization_id = o.id) AS appointments_count,
                (SELECT count(*) FROM appointments a
                   WHERE a.organization_id = o.id
                     AND a.start_at >= now() - interval '30 days') AS appt_30d,
                (SELECT count(*) FROM payments p
                   WHERE p.organization_id = o.id) AS payments_count,
                (SELECT count(*) FROM expenses e
                   WHERE e.organization_id = o.id) AS expenses_count,
                (o.monthly_revenue_goal IS NOT NULL) AS has_revenue_goal,
                GREATEST(
                    (SELECT max(a.start_at) FROM appointments a WHERE a.organization_id = o.id),
                    (SELECT max(m.created_at) FROM messages m WHERE m.organization_id = o.id)
                ) AS last_activity,
                s.status::text AS sub_status,
                s.current_period_end AS sub_period_end
            FROM organizations o
            LEFT JOIN LATERAL (
                SELECT status, current_period_end FROM subscriptions
                WHERE organization_id = o.id
                ORDER BY created_at DESC LIMIT 1
            ) s ON true
            WHERE o.deleted_at IS NULL
            ORDER BY o.id
        $$
        """
    )

    # ── overrides (leitura em lote + upsert + clear) ─────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_onboarding_overrides()
        RETURNS TABLE(organization_id bigint, stage_key text, done boolean)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT organization_id, stage_key, done
            FROM platform_onboarding_overrides
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_onboarding_override_set(
            p_org_id bigint, p_stage_key text, p_done boolean, p_admin_id bigint
        )
        RETURNS TABLE(organization_id bigint, stage_key text, done boolean)
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            INSERT INTO platform_onboarding_overrides
                (organization_id, stage_key, done, admin_id, admin_email)
            SELECT p_org_id, p_stage_key, p_done, pa.id, pa.email
            FROM platform_admins pa
            WHERE pa.id = p_admin_id
            ON CONFLICT (organization_id, stage_key) DO UPDATE
                SET done = EXCLUDED.done,
                    admin_id = EXCLUDED.admin_id,
                    admin_email = EXCLUDED.admin_email,
                    created_at = now()
            RETURNING organization_id, stage_key, done
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_onboarding_override_clear(
            p_org_id bigint, p_stage_key text
        )
        RETURNS bigint
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH del AS (
                DELETE FROM platform_onboarding_overrides
                WHERE organization_id = p_org_id AND stage_key = p_stage_key
                RETURNING id
            )
            SELECT count(*)::bigint FROM del
        $$
        """
    )

    for fn in _FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO barber_app")


def downgrade() -> None:
    for fn in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.drop_table("platform_onboarding_overrides")
