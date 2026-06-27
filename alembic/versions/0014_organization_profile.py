"""perfil cadastral da organização (dados de empresa)

Revision ID: 0014_organization_profile
Revises: 0013_grant_membership_tables
Create Date: 2026-06-26

Adiciona campos cadastrais à organização para a tela /admin/empresa:
razão social, CNPJ, contato (telefone/email), site/instagram e logo.
Todas as colunas são nullable — retrocompatível com orgs existentes.

`organizations` foi criada na migration inicial e já recebeu GRANT no
provisionamento do banco; colunas novas herdam o UPDATE em nível de tabela.
O GRANT abaixo é defensivo/idempotente (mesma postura de 0011/0013) — garante
que o app possa atualizar a org mesmo em ambientes onde o grant inicial
tenha sido só de SELECT.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_organization_profile"
down_revision = "0013_grant_membership_tables"
branch_labels = None
depends_on = None

_COLUMNS = (
    "legal_name",
    "cnpj",
    "phone",
    "email",
    "website",
    "instagram",
    "logo_url",
)


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column("organizations", sa.Column(col, sa.Text(), nullable=True))
    op.execute("GRANT SELECT, UPDATE ON organizations TO barber_app")


def downgrade() -> None:
    for col in reversed(_COLUMNS):
        op.drop_column("organizations", col)
