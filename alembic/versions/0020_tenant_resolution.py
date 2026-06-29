"""resolução de tenant — subdomínio (login) e instância WhatsApp (bot)

Revision ID: 0020_tenant_resolution
Revises: 0019_gestor_fields
Create Date: 2026-06-29

Fundação do multi-tenant real (remoção do org_id hardcoded). Tudo ADITIVO e
retrocompatível — colunas nullable, backfill posterior por org.

- `organizations.subdomain` — slug do tenant no login (ex.: `taylor` →
  `taylor.app.com`). O frontend resolve o subdomínio do host → org_id antes do
  login (substitui `NEXT_PUBLIC_ORG_ID`). Único quando não-nulo.
- `organizations.wa_instance_name` — nome da instância Evolution/WhatsApp que
  recebe os webhooks daquela barbearia. O bot resolve a org pela instância do
  payload (multi-tenant), com fallback a `settings.bot_organization_id` enquanto
  a coluna estiver NULL (prod intacto até o backfill). Único quando não-nulo.

Resolução PRÉ-TENANT: subdomínio/instância são consultados ANTES de saber a org,
mas `organizations` tem RLS por `app.current_org_id` — um SELECT sem tenant não
enxerga linha alguma. Por isso duas funções `SECURITY DEFINER` (rodam como dono
→ ignoram a RLS) que devolvem APENAS o `id` (bigint). Não vazam dados da linha
além de existência + id. `GRANT EXECUTE` ao role do app (`barber_app`).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0020_tenant_resolution"
down_revision = "0019_gestor_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── colunas de resolução de tenant ───────────────────────────────────────
    op.add_column("organizations", sa.Column("subdomain", sa.Text(), nullable=True))
    op.add_column(
        "organizations", sa.Column("wa_instance_name", sa.Text(), nullable=True)
    )
    # Índice em lower(subdomain): unicidade e resolução são case-insensitive
    # (a função app_org_id_by_subdomain compara por lower()).
    op.create_index(
        "idx_organizations_subdomain",
        "organizations",
        [sa.text("lower(subdomain)")],
        unique=True,
        postgresql_where=sa.text("subdomain IS NOT NULL"),
    )
    op.create_index(
        "idx_organizations_wa_instance",
        "organizations",
        ["wa_instance_name"],
        unique=True,
        postgresql_where=sa.text("wa_instance_name IS NOT NULL"),
    )

    # ── resolução pré-tenant via SECURITY DEFINER (ignora a RLS, devolve só id) ─
    # search_path travado (defesa contra hijack de objetos) e STABLE (sem efeito
    # colateral, cacheável por statement). Casefold no subdomínio (case-insensitive).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_org_id_by_subdomain(p_subdomain text)
        RETURNS bigint
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT id FROM organizations
            WHERE lower(subdomain) = lower(p_subdomain)
              AND deleted_at IS NULL
            LIMIT 1
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_org_id_by_wa_instance(p_instance text)
        RETURNS bigint
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT id FROM organizations
            WHERE wa_instance_name = p_instance
              AND deleted_at IS NULL
            LIMIT 1
        $$
        """
    )
    # Sem GRANT, o role do app não consegue executar a função.
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_org_id_by_subdomain(text) TO barber_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_org_id_by_wa_instance(text) TO barber_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_org_id_by_wa_instance(text)")
    op.execute("DROP FUNCTION IF EXISTS app_org_id_by_subdomain(text)")
    op.drop_index("idx_organizations_wa_instance", table_name="organizations")
    op.drop_index("idx_organizations_subdomain", table_name="organizations")
    op.drop_column("organizations", "wa_instance_name")
    op.drop_column("organizations", "subdomain")
