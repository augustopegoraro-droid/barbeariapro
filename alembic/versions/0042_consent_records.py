"""histórico de consentimento (LGPD) + anonimização de cliente (Fase 8)

Revision ID: 0042_consent_records
Revises: 0041_client_visibility_settings
Create Date: 2026-07-09

Cria `consent_records` (ARQUITETURA_ALVO.md §1.11): histórico APPEND-ONLY de
consentimento — evolui `client_consents` (D-51, tabela de ESTADO atual, uma
linha por cliente+canal, sobrescrita a cada mudança) sem substituí-la:
`client_consents` continua sendo a fonte rápida que `reminders.py`/
`reactivation.py` já leem; `consent_records` é o log completo de cada mudança
(o quê, quando, origem, IP), necessário para provar consentimento/opt-out
numa auditoria de verdade.

Também adiciona `clients.anonymized_at` (aditivo) — marca se/quando um
cliente foi anonimizado a pedido do titular (direito ao esquecimento),
preservando agregados financeiros (Payment/AppointmentItem não são tocados,
só o PII do próprio `Client`).

Molde `audit_logs` (0039): RLS + FORCE explícito, append-only (só
SELECT/INSERT para `barber_app`).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0042_consent_records"
down_revision = "0041_client_visibility_settings"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("anonymized_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_table(
        "consent_records",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.Text, nullable=False),
        sa.Column("subject_id", sa.BigInteger, nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("policy_version", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "subject_type IN ('client', 'lead', 'user')", name="consent_records_subject_type_valid"
        ),
    )
    op.create_index(
        "idx_consent_records_org_subject", "consent_records", ["organization_id", "subject_type", "subject_id"]
    )
    op.create_index("idx_consent_records_org_created", "consent_records", ["organization_id", "created_at"])

    op.execute("ALTER TABLE consent_records ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON consent_records "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE consent_records FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON consent_records TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON consent_records")
    op.execute("ALTER TABLE consent_records DISABLE ROW LEVEL SECURITY")
    op.drop_table("consent_records")
    op.drop_column("clients", "anonymized_at")
