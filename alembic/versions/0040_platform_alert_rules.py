"""regras configuráveis da Central de Operações (superadmin M11)

Revision ID: 0040_platform_alert_rules
Revises: 0039_audit_logs
Create Date: 2026-07-09

Aditivo. `platform_alert_rules` no molde ESTRITO de `platform_admins`: sem RLS
e SEM GRANT ao `barber_app` — leitura/escrita só via SECURITY DEFINER. Uma
linha por regra (kind único), semeada com os limiares que estavam hardcoded
no GET /platform/alerts (SA-D10) + a regra nova `health_at_risk` (D-69).
CHECKs espelhados no ORM (D-60).

Semântica do `threshold` por kind:
  payment_overdue   → alerta quando days_overdue ≥ N (dias)
  trial_ending      → alerta quando restam ≤ N dias de trial
  onboarding_stuck  → alerta quando parado há > N dias
  inactive_account  → conta pagante sem atividade há ≥ N dias
  webhook_failures  → alerta quando há ≥ N webhooks de billing falhos
  health_at_risk    → alerta quando o health score fica < N (pontos)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0040_platform_alert_rules"
down_revision = "0039_audit_logs"
branch_labels = None
depends_on = None

_KINDS = (
    "payment_overdue", "trial_ending", "onboarding_stuck",
    "inactive_account", "webhook_failures", "health_at_risk",
)

# (kind, enabled, threshold, severity) — comportamento idêntico ao hardcoded.
_SEED = (
    ("payment_overdue", True, 1, "critical"),
    ("trial_ending", True, 7, "warning"),
    ("onboarding_stuck", True, 7, "warning"),
    ("inactive_account", True, 30, "warning"),
    ("webhook_failures", True, 1, "critical"),
    ("health_at_risk", True, 40, "warning"),
)

_FUNCTIONS = (
    "app_platform_alert_rules_list()",
    "app_platform_alert_rule_set(text, boolean, int, text, bigint)",
)


def upgrade() -> None:
    kinds_sql = ", ".join(f"'{k}'" for k in _KINDS)
    op.create_table(
        "platform_alert_rules",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.UniqueConstraint("kind", name="platform_alert_rules_kind_unique"),
        sa.CheckConstraint(
            f"kind IN ({kinds_sql})", name="platform_alert_rules_kind_valid"
        ),
        sa.CheckConstraint(
            "threshold >= 0 AND threshold <= 1000",
            name="platform_alert_rules_threshold_range",
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name="platform_alert_rules_severity_valid",
        ),
    )
    # Intencional: SEM RLS e SEM GRANT (molde platform_admins).

    rows = ", ".join(
        f"('{k}', {str(e).lower()}, {t}, '{s}')" for k, e, t, s in _SEED
    )
    op.execute(
        f"INSERT INTO platform_alert_rules (kind, enabled, threshold, severity) VALUES {rows}"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_alert_rules_list()
        RETURNS TABLE(
            kind text, enabled boolean, threshold int, severity text,
            updated_at timestamptz, updated_by text
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT kind, enabled, threshold, severity, updated_at, updated_by
            FROM platform_alert_rules
            ORDER BY id
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_platform_alert_rule_set(
            p_kind text, p_enabled boolean, p_threshold int,
            p_severity text, p_admin_id bigint
        )
        RETURNS TABLE(
            kind text, enabled boolean, threshold int, severity text,
            updated_at timestamptz, updated_by text
        )
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            UPDATE platform_alert_rules r
            SET enabled = p_enabled, threshold = p_threshold,
                severity = p_severity, updated_at = now(), updated_by = pa.email
            FROM platform_admins pa
            WHERE pa.id = p_admin_id AND r.kind = p_kind
            RETURNING r.kind, r.enabled, r.threshold, r.severity,
                      r.updated_at, r.updated_by
        $$
        """
    )
    for fn in _FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO barber_app")


def downgrade() -> None:
    for fn in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.drop_table("platform_alert_rules")
