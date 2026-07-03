"""detalhe 360° da barbearia + notas internas do superadmin (superadmin M5)

Revision ID: 0030_platform_org_detail
Revises: 0029_platform_org_overview
Create Date: 2026-07-03

Aditivo.

- `platform_org_notes` — notas internas do time da plataforma sobre uma org
  (suporte/CS). Segue o molde de `platform_admins`: SEM RLS e SEM GRANT ao
  `barber_app` — o tenant nunca enxerga; todo acesso via SECURITY DEFINER.
  CHECK espelhado no ORM (D-60): corpo não pode ser vazio/só espaços.

- Funções `SECURITY DEFINER` de leitura do detalhe (molde 0021): perfil completo
  da org (cadastro + assinatura vigente + plano), usuários (com papéis),
  profissionais, histórico de assinaturas e notas; escrita de nota.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0030_platform_org_detail"
down_revision = "0029_platform_org_overview"
branch_labels = None
depends_on = None

_FUNCTIONS = (
    "app_platform_org_profile(bigint)",
    "app_platform_org_users(bigint)",
    "app_platform_org_barbers(bigint)",
    "app_platform_org_subscriptions(bigint)",
    "app_platform_org_notes_list(bigint)",
    "app_platform_org_note_add(bigint, bigint, text)",
)


def upgrade() -> None:
    op.create_table(
        "platform_org_notes",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "admin_id",
            sa.BigInteger,
            sa.ForeignKey("platform_admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("admin_email", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(btrim(body)) > 0", name="platform_org_notes_body_nonempty"
        ),
    )
    op.create_index(
        "idx_platform_org_notes_org", "platform_org_notes", ["organization_id"]
    )
    # Intencional (molde platform_admins): SEM RLS e SEM GRANT a barber_app.

    # ── perfil completo (cadastro + assinatura mais recente + plano) ─────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_org_profile(p_org_id bigint)
        RETURNS TABLE(
            id bigint, public_id uuid, name text, subdomain text,
            wa_instance_name text, legal_name text, cnpj text, phone text,
            email text, website text, instagram text, logo_url text,
            monthly_revenue_goal numeric, created_at timestamptz, deleted_at timestamptz,
            sub_id bigint, sub_status text, sub_period_start timestamptz,
            sub_period_end timestamptz, sub_canceled_at timestamptz,
            plan_id bigint, plan_name text, plan_price_month numeric,
            plan_max_units integer, plan_max_barbers integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT o.id, o.public_id, o.name, o.subdomain,
                   o.wa_instance_name, o.legal_name, o.cnpj, o.phone,
                   o.email, o.website, o.instagram, o.logo_url,
                   o.monthly_revenue_goal, o.created_at, o.deleted_at,
                   s.id AS sub_id, s.status::text AS sub_status,
                   s.current_period_start AS sub_period_start,
                   s.current_period_end AS sub_period_end,
                   s.canceled_at AS sub_canceled_at,
                   p.id AS plan_id, p.name AS plan_name,
                   p.price_month AS plan_price_month,
                   p.max_units AS plan_max_units, p.max_barbers AS plan_max_barbers
            FROM organizations o
            LEFT JOIN LATERAL (
                SELECT * FROM subscriptions
                WHERE organization_id = o.id
                ORDER BY created_at DESC LIMIT 1
            ) s ON true
            LEFT JOIN plans p ON p.id = s.plan_id
            WHERE o.id = p_org_id
        $$
        """
    )

    # ── usuários da org (com papéis agregados das unidades) ──────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_org_users(p_org_id bigint)
        RETURNS TABLE(
            id bigint, email text, phone_e164 text, is_active boolean,
            created_at timestamptz, roles text[]
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT u.id, u.email, u.phone_e164, u.is_active, u.created_at,
                   (SELECT array_agg(DISTINCT uu.role::text)
                      FROM user_units uu
                      JOIN units un ON un.id = uu.unit_id
                     WHERE uu.user_id = u.id
                       AND un.organization_id = u.organization_id) AS roles
            FROM users u
            WHERE u.organization_id = p_org_id AND u.deleted_at IS NULL
            ORDER BY u.id
        $$
        """
    )

    # ── profissionais da org ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_org_barbers(p_org_id bigint)
        RETURNS TABLE(
            id bigint, name text, specialty text, work_model text,
            commission_pct numeric, created_at timestamptz, deleted_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT b.id, b.name, b.specialty, b.work_model,
                   b.commission_pct, b.created_at, b.deleted_at
            FROM barbers b
            WHERE b.organization_id = p_org_id
            ORDER BY (b.deleted_at IS NOT NULL), b.name
        $$
        """
    )

    # ── histórico de assinaturas ─────────────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_org_subscriptions(p_org_id bigint)
        RETURNS TABLE(
            id bigint, plan_id bigint, plan_name text, plan_price_month numeric,
            status text, current_period_start timestamptz,
            current_period_end timestamptz, canceled_at timestamptz,
            created_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT s.id, s.plan_id, p.name AS plan_name,
                   p.price_month AS plan_price_month,
                   s.status::text, s.current_period_start,
                   s.current_period_end, s.canceled_at, s.created_at
            FROM subscriptions s
            LEFT JOIN plans p ON p.id = s.plan_id
            WHERE s.organization_id = p_org_id
            ORDER BY s.created_at DESC
        $$
        """
    )

    # ── notas internas (leitura + escrita) ───────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_org_notes_list(p_org_id bigint)
        RETURNS TABLE(
            id bigint, admin_id bigint, admin_email text, body text,
            created_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT n.id, n.admin_id, n.admin_email, n.body, n.created_at
            FROM platform_org_notes n
            WHERE n.organization_id = p_org_id
            ORDER BY n.created_at DESC, n.id DESC
        $$
        """
    )
    # Snapshot do e-mail resolvido DENTRO da função (SECURITY DEFINER lê
    # platform_admins); se o admin não existir, não insere nada (retorna vazio).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_org_note_add(
            p_org_id bigint, p_admin_id bigint, p_body text
        )
        RETURNS TABLE(
            id bigint, admin_id bigint, admin_email text, body text,
            created_at timestamptz
        )
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            INSERT INTO platform_org_notes (organization_id, admin_id, admin_email, body)
            SELECT p_org_id, pa.id, pa.email, p_body
            FROM platform_admins pa
            WHERE pa.id = p_admin_id
            RETURNING id, admin_id, admin_email, body, created_at
        $$
        """
    )

    for fn in _FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO barber_app")


def downgrade() -> None:
    for fn in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.drop_index("idx_platform_org_notes_org", table_name="platform_org_notes")
    op.drop_table("platform_org_notes")
