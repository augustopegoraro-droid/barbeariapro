"""configurações de visibilidade do site público do cliente final (Fase 6)

Revision ID: 0041_client_visibility_settings
Revises: 0040_platform_alert_rules
Create Date: 2026-07-09

Cria `client_visibility_settings` (ARQUITETURA_ALVO.md §1.9): 1 linha por
org, controlando o que aparecerá no site público de agendamento (serviços,
profissionais, horários, avaliações, promoções, banner, dados públicos).

O site público em si **ainda não existe** no produto (confirmado na
Fase 0 da auditoria de segurança) — esta migration só entrega a
CONFIGURAÇÃO (gerida pelo gestor, `security.site_visibility.manage`, já no
catálogo desde o D-67). Não há endpoint público de leitura ainda; será
adicionado quando o site público entrar no roadmap do produto, reusando
`app_org_id_by_subdomain` (D-54) para resolver a org sem tenant.

RLS com FORCE explícito, molde 0039/0040 (a tabela nasce depois do loop
dinâmico de 0038, não é coberta por ele).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0041_client_visibility_settings"
down_revision = "0040_platform_alert_rules"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    op.create_table(
        "client_visibility_settings",
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "services", JSONB, nullable=False,
            server_default=sa.text('\'{"mode":"all","ids":[]}\'::jsonb'),
        ),
        sa.Column(
            "professionals", JSONB, nullable=False,
            server_default=sa.text('\'{"mode":"all","ids":[]}\'::jsonb'),
        ),
        sa.Column("show_hours", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_reviews", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_promotions", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "banner", JSONB, nullable=False,
            # `:false` seria lido como bind param pelo sa.text() — literal_column
            # não faz esse parsing.
            server_default=sa.literal_column('\'{"enabled": false}\'::jsonb'),
        ),
        sa.Column(
            "public_info", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "updated_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("ALTER TABLE client_visibility_settings ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON client_visibility_settings "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE client_visibility_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON client_visibility_settings TO barber_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON client_visibility_settings")
    op.execute("ALTER TABLE client_visibility_settings DISABLE ROW LEVEL SECURITY")
    op.drop_table("client_visibility_settings")
