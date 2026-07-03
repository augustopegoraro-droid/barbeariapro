"""visão cross-org de assinaturas com dunning para o painel (superadmin M8)

Revision ID: 0033_platform_billing_view
Revises: 0032_billing_domain
Create Date: 2026-07-03

Aditivo. Uma função SECURITY DEFINER (molde 0021): assinatura mais recente por
org + plano + inadimplência (faturas abertas, valor em aberto, dias de atraso,
última tentativa de cobrança e próximo retry). `webhook_events`/`coupons` não
precisam de função — não têm RLS e o app tem GRANT.
"""
from __future__ import annotations

from alembic import op

revision = "0033_platform_billing_view"
down_revision = "0032_billing_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_billing_subscriptions()
        RETURNS TABLE(
            org_id bigint, org_name text, org_deleted_at timestamptz,
            sub_id bigint, status text, provider text,
            cancel_at_period_end boolean,
            current_period_end timestamptz, trial_end timestamptz,
            plan_id bigint, plan_name text, plan_price_month numeric,
            open_invoices bigint, open_amount numeric,
            days_overdue integer, last_attempt integer,
            last_attempt_error text, next_retry_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT
                o.id AS org_id, o.name AS org_name, o.deleted_at AS org_deleted_at,
                s.id AS sub_id, s.status::text AS status, s.provider,
                s.cancel_at_period_end,
                s.current_period_end, s.trial_end,
                p.id AS plan_id, p.name AS plan_name, p.price_month AS plan_price_month,
                COALESCE(inv.open_invoices, 0) AS open_invoices,
                COALESCE(inv.open_amount, 0) AS open_amount,
                COALESCE(inv.days_overdue, 0) AS days_overdue,
                att.attempt_number AS last_attempt,
                att.provider_error_message AS last_attempt_error,
                att.next_retry_at
            FROM organizations o
            JOIN LATERAL (
                SELECT * FROM subscriptions
                WHERE organization_id = o.id
                ORDER BY created_at DESC, id DESC LIMIT 1
            ) s ON true
            LEFT JOIN plans p ON p.id = s.plan_id
            LEFT JOIN LATERAL (
                SELECT count(*) AS open_invoices,
                       sum(amount_due - amount_paid) AS open_amount,
                       GREATEST(
                           EXTRACT(day FROM now() - min(COALESCE(due_date, created_at)))::int, 0
                       ) AS days_overdue
                FROM invoices i
                WHERE i.organization_id = o.id
                  AND i.status IN ('open', 'uncollectible')
            ) inv ON true
            LEFT JOIN LATERAL (
                SELECT pa.attempt_number, pa.provider_error_message, pa.next_retry_at
                FROM payment_attempts pa
                WHERE pa.organization_id = o.id
                ORDER BY pa.created_at DESC, pa.id DESC LIMIT 1
            ) att ON true
            ORDER BY COALESCE(inv.days_overdue, 0) DESC, o.name
        $$
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_platform_billing_subscriptions() TO barber_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_platform_billing_subscriptions()")
