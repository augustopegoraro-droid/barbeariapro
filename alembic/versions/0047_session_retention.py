"""Retenção de sessões: purga de `sessions` e `client_sessions` — D-86.

O D-68 (staff) e o D-79 (cliente final) criaram sessões que guardam IP e
user-agent — dado pessoal — e **nunca** eram apagadas: sessão revogada há um
ano continuava na tabela, e o cookie do site público vive 400 dias. Sem purga,
"retenção" não existe para esses dados.

Molde da `app_audit_purge_expired` (0039): função `SECURITY DEFINER` porque a
purga é cross-org e o role da app é NOBYPASSRLS — um DELETE sem tenant setado
não veria linha nenhuma.

Critério (parâmetros em meses/dias vêm da chamada, não do banco, para não
inventar coluna nova):
- sessão revogada/expirada há mais de `p_grace_days` → apagada;
- sessão viva mas sem uso há mais de `p_idle_days` → apagada (o cookie já não
  vale nada; guardar o IP dele é retenção sem finalidade).

Revision ID: 0047
Revises: 0046
"""

from alembic import op

revision = "0047_session_retention"
down_revision = "0046_audit_actor_kind_client"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_sessions_purge_expired(
            p_grace_days integer,
            p_staff_idle_days integer,
            p_client_idle_days integer
        )
        RETURNS TABLE(staff_deleted bigint, client_deleted bigint)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH staff AS (
                DELETE FROM sessions s
                WHERE (s.revoked_at IS NOT NULL
                       AND s.revoked_at < now() - (p_grace_days || ' days')::interval)
                   OR s.refresh_expires_at < now() - (p_grace_days || ' days')::interval
                   OR s.last_seen_at < now() - (p_staff_idle_days || ' days')::interval
                RETURNING s.id
            ), clients AS (
                DELETE FROM client_sessions c
                WHERE (c.revoked_at IS NOT NULL
                       AND c.revoked_at < now() - (p_grace_days || ' days')::interval)
                   OR c.last_seen_at < now() - (p_client_idle_days || ' days')::interval
                RETURNING c.id
            )
            SELECT (SELECT count(*) FROM staff), (SELECT count(*) FROM clients)
        $$
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_sessions_purge_expired(integer, integer, integer) "
        "TO barber_app"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS app_sessions_purge_expired(integer, integer, integer)"
    )
