"""painel de plataforma (superadmin): platform_admins + funções cross-tenant

Revision ID: 0021_platform_superadmin
Revises: 0020_tenant_resolution
Create Date: 2026-06-29

Camada ACIMA dos tenants (dono do SaaS). Tudo ADITIVO.

- `platform_admins` — usuário GLOBAL do SaaS (sem `organization_id`, SEM RLS).
  É conceitualmente separado de `users` (que opera UMA barbearia). NÃO recebe
  GRANT ao role do app (`barber_app`): o app nunca lê a tabela direto. O acesso
  é só via funções `SECURITY DEFINER` abaixo (rodam como dono → ignoram a RLS),
  no mesmo molde da migration 0020 (subdomínio/instância).

- Funções `SECURITY DEFINER` cross-tenant (a role do app é NOBYPASSRLS; um SELECT
  cross-org sem `app.current_org_id` retorna 0 linhas). Devolvem só o necessário:
  login do superadmin, listagem/uso agregado das orgs e criação de org (onboarding).
  `GRANT EXECUTE ... TO barber_app`.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0021_platform_superadmin"
down_revision = "0020_tenant_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tabela global de superadmins (sem org_id, sem RLS) ───────────────────
    op.create_table(
        "platform_admins",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="platform_admins_email_unique"),
    )
    # Intencional: SEM ENABLE ROW LEVEL SECURITY (tabela global) e SEM GRANT a
    # barber_app — acesso só pelas funções SECURITY DEFINER.

    # ── login / revalidação do superadmin ────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_admin_login(p_email text)
        RETURNS TABLE(id bigint, password_hash text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT id, password_hash FROM platform_admins
            WHERE email = lower(p_email) LIMIT 1
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_admin_exists(p_id bigint)
        RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$ SELECT id FROM platform_admins WHERE id = p_id LIMIT 1 $$
        """
    )

    # ── listagem de TODAS as orgs (com plano + status da assinatura) ─────────
    # Pega a assinatura mais recente por org (DISTINCT ON). Cross-tenant.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_list_orgs()
        RETURNS TABLE(
            id bigint, name text, subdomain text, plan_name text,
            plan_price_month numeric, sub_status text,
            created_at timestamptz, deleted_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT o.id, o.name, o.subdomain, p.name AS plan_name,
                   p.price_month AS plan_price_month,
                   s.status::text AS sub_status, o.created_at, o.deleted_at
            FROM organizations o
            LEFT JOIN LATERAL (
                SELECT status, plan_id FROM subscriptions
                WHERE organization_id = o.id
                ORDER BY created_at DESC LIMIT 1
            ) s ON true
            LEFT JOIN plans p ON p.id = s.plan_id
            ORDER BY o.id
        $$
        """
    )

    # ── ids das orgs ativas (deleted_at NULL) — base do loop de MRR ──────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_active_org_ids()
        RETURNS SETOF bigint
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id
        $$
        """
    )

    # ── uso por tenant (cross-org) p/ detectar churn ─────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_usage()
        RETURNS TABLE(
            org_id bigint, appt_30d bigint, active_users bigint,
            bot_msgs_30d bigint, last_activity timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT
                o.id AS org_id,
                (SELECT count(*) FROM appointments a
                   WHERE a.organization_id = o.id
                     AND a.start_at >= now() - interval '30 days') AS appt_30d,
                (SELECT count(*) FROM users u
                   WHERE u.organization_id = o.id AND u.is_active) AS active_users,
                (SELECT count(*) FROM messages m
                   WHERE m.organization_id = o.id
                     AND m.sender_type = 'bot'
                     AND m.created_at >= now() - interval '30 days') AS bot_msgs_30d,
                GREATEST(
                    (SELECT max(a.start_at) FROM appointments a WHERE a.organization_id = o.id),
                    (SELECT max(m.created_at) FROM messages m WHERE m.organization_id = o.id)
                ) AS last_activity
            FROM organizations o
            WHERE o.deleted_at IS NULL
            ORDER BY o.id
        $$
        """
    )

    # ── onboarding: cria organização + assinatura, devolve o novo org_id ─────
    # Os filhos (unidade/owner/serviços) são semeados pela camada Python sob a
    # org recém-criada (set_current_org em sessão helper).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_create_org(
            p_name text, p_subdomain text, p_plan_id bigint
        )
        RETURNS bigint
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_org_id bigint;
        BEGIN
            INSERT INTO organizations (name, subdomain)
            VALUES (p_name, lower(nullif(p_subdomain, '')))
            RETURNING id INTO v_org_id;

            INSERT INTO subscriptions (
                organization_id, plan_id, status,
                current_period_start, current_period_end
            )
            VALUES (
                v_org_id, p_plan_id, 'trial',
                now(), now() + interval '365 days'
            );

            RETURN v_org_id;
        END
        $$
        """
    )

    for fn in (
        "app_platform_admin_login(text)",
        "app_platform_admin_exists(bigint)",
        "app_platform_list_orgs()",
        "app_platform_active_org_ids()",
        "app_platform_usage()",
        "app_platform_create_org(text, text, bigint)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO barber_app")


def downgrade() -> None:
    for fn in (
        "app_platform_create_org(text, text, bigint)",
        "app_platform_usage()",
        "app_platform_active_org_ids()",
        "app_platform_list_orgs()",
        "app_platform_admin_exists(bigint)",
        "app_platform_admin_login(text)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.drop_table("platform_admins")
