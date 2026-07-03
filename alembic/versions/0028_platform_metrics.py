"""métricas executivas da plataforma: série mensal cross-tenant (superadmin M3)

Revision ID: 0028_platform_metrics
Revises: 0027_reschedule_and_cost_checks
Create Date: 2026-07-03

Aditivo. Uma função `SECURITY DEFINER` (molde da 0021) que devolve a série
mensal de crescimento do SaaS: novas orgs, assinaturas canceladas, base ativa/
trial e MRR ao fim de cada mês.

Limitação documentada: antes das faturas (invoices, milestone M7 do superadmin)
não existe histórico de transições de status — a série usa a VIGÊNCIA da
assinatura (created_at/canceled_at) combinada com o status ATUAL. É uma
aproximação honesta do passado e fica exata para os meses novos assim que o
billing real entrar. Receita realizada por período virá de `invoices`.
"""
from __future__ import annotations

from alembic import op

revision = "0028_platform_metrics"
down_revision = "0027_reschedule_and_cost_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_metrics_monthly(p_months int)
        RETURNS TABLE(
            month date, new_orgs bigint, canceled_subs bigint,
            active_subs bigint, trial_subs bigint, mrr numeric
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH bounds AS (
                SELECT
                    (date_trunc('month', now()) - make_interval(months => gs.i)) AS month_start,
                    (date_trunc('month', now()) - make_interval(months => gs.i)
                        + interval '1 month') AS month_end
                FROM generate_series(GREATEST(LEAST(p_months, 36), 1) - 1, 0, -1) AS gs(i)
            )
            SELECT
                b.month_start::date AS month,
                (SELECT count(*) FROM organizations o
                  WHERE o.created_at >= b.month_start
                    AND o.created_at < b.month_end) AS new_orgs,
                (SELECT count(*) FROM subscriptions s
                  WHERE s.canceled_at >= b.month_start
                    AND s.canceled_at < b.month_end) AS canceled_subs,
                (SELECT count(*) FROM subscriptions s
                  WHERE s.created_at < b.month_end
                    AND (s.canceled_at IS NULL OR s.canceled_at >= b.month_end)
                    AND s.status = 'active') AS active_subs,
                (SELECT count(*) FROM subscriptions s
                  WHERE s.created_at < b.month_end
                    AND (s.canceled_at IS NULL OR s.canceled_at >= b.month_end)
                    AND s.status = 'trial') AS trial_subs,
                COALESCE((SELECT sum(p.price_month)
                  FROM subscriptions s
                  JOIN plans p ON p.id = s.plan_id
                  WHERE s.created_at < b.month_end
                    AND (s.canceled_at IS NULL OR s.canceled_at >= b.month_end)
                    AND s.status = 'active'), 0) AS mrr
            FROM bounds b
            ORDER BY month
        $$
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_platform_metrics_monthly(int) TO barber_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_platform_metrics_monthly(int)")
