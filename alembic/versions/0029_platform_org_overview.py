"""visão rica por org para a gestão de barbearias (superadmin M4)

Revision ID: 0029_platform_org_overview
Revises: 0028_platform_metrics
Create Date: 2026-07-03

Aditivo. Função `SECURITY DEFINER` (molde 0021) que devolve, por organização,
os campos que a tabela de gestão do painel precisa numa chamada só: plano,
assinatura mais recente (status + fim do período), contagens (usuários ativos,
profissionais, clientes), agendamentos 30d e última atividade.

Não substitui `app_platform_list_orgs()` (mantida por retrocompatibilidade —
consumida por /platform/orgs, dashboard e releituras internas).
"""
from __future__ import annotations

from alembic import op

revision = "0029_platform_org_overview"
down_revision = "0028_platform_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_org_overview()
        RETURNS TABLE(
            id bigint, name text, subdomain text,
            plan_id bigint, plan_name text, plan_price_month numeric,
            sub_status text, sub_period_end timestamptz,
            created_at timestamptz, deleted_at timestamptz,
            users_count bigint, barbers_count bigint, clients_count bigint,
            appt_30d bigint, last_activity timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT
                o.id, o.name, o.subdomain,
                p.id AS plan_id, p.name AS plan_name,
                p.price_month AS plan_price_month,
                s.status::text AS sub_status,
                s.current_period_end AS sub_period_end,
                o.created_at, o.deleted_at,
                (SELECT count(*) FROM users u
                   WHERE u.organization_id = o.id AND u.is_active) AS users_count,
                (SELECT count(*) FROM barbers b
                   WHERE b.organization_id = o.id AND b.deleted_at IS NULL) AS barbers_count,
                (SELECT count(*) FROM clients c
                   WHERE c.organization_id = o.id) AS clients_count,
                (SELECT count(*) FROM appointments a
                   WHERE a.organization_id = o.id
                     AND a.start_at >= now() - interval '30 days') AS appt_30d,
                GREATEST(
                    (SELECT max(a.start_at) FROM appointments a
                       WHERE a.organization_id = o.id),
                    (SELECT max(m.created_at) FROM messages m
                       WHERE m.organization_id = o.id)
                ) AS last_activity
            FROM organizations o
            LEFT JOIN LATERAL (
                SELECT status, plan_id, current_period_end FROM subscriptions
                WHERE organization_id = o.id
                ORDER BY created_at DESC LIMIT 1
            ) s ON true
            LEFT JOIN plans p ON p.id = s.plan_id
            ORDER BY o.id
        $$
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_platform_org_overview() TO barber_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_platform_org_overview()")
