"""pacote personalizado por cliente — client_memberships.plan_id nullable

Revision ID: 0015_client_membership_custom
Revises: 0014_organization_profile
Create Date: 2026-06-27

Habilita assinaturas personalizadas por cliente (combo/usos/preço/duração
montados na venda, com ou sem plano de catálogo de base). A única amarra
rígida ao catálogo era `plan_id NOT NULL`; tornando-o nullable, um pacote
custom é gravado como `ClientMembership` com `plan_id = NULL` — todos os dados
já vivem nos snapshots imutáveis (`combo_snapshot`, `included_uses`,
`unit_recognized_value`, `price_paid`, `duration_days`).

Mudança aditiva/retrocompatível: assinaturas existentes mantêm seu `plan_id`.
A tabela `client_memberships` já recebeu RLS + GRANT (0012/0013); afrouxar a
nullability de uma coluna não exige novo GRANT/policy.
"""
from __future__ import annotations

from alembic import op

revision = "0015_client_membership_custom"
down_revision = "0014_organization_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("client_memberships", "plan_id", nullable=True)


def downgrade() -> None:
    # Só volta a NOT NULL se não houver pacotes personalizados gravados.
    op.alter_column("client_memberships", "plan_id", nullable=False)
