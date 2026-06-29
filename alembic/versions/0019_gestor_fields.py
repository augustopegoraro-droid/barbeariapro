"""tools de gestão — telefone do usuário (gating) + meta de faturamento

Revision ID: 0019_gestor_fields
Revises: 0018_membership_corrections
Create Date: 2026-06-28

Fundação das "tools de gestão" (Agente Gestor, D-52). Tudo ADITIVO e
retrocompatível:

- `users.phone_e164` — telefone canônico (E.164) do usuário. Usado para o gating
  por telefone: o Agente Gestor cruza o número do remetente (WhatsApp) com a role
  do User (owner/manager) antes de liberar dados sensíveis. NULL para usuários
  antigos; índice parcial único por organização evita dois usuários com o mesmo
  telefone na mesma org (não bloqueia NULLs).
- `organizations.monthly_revenue_goal` — meta de faturamento mensal (R$) usada
  pelo alerta proativo de meta. NULL = sem meta definida (alerta desligado).

`users` e `organizations` já têm RLS + GRANT; `ADD COLUMN`/índice não exigem novo
GRANT.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0019_gestor_fields"
down_revision = "0018_membership_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── telefone canônico do usuário (gating do Agente Gestor) ───────────────
    op.add_column("users", sa.Column("phone_e164", sa.Text(), nullable=True))
    op.create_index(
        "idx_users_phone_per_org",
        "users",
        ["organization_id", "phone_e164"],
        unique=True,
        postgresql_where=sa.text("phone_e164 IS NOT NULL"),
    )

    # ── meta de faturamento mensal (alerta proativo) ─────────────────────────
    op.add_column(
        "organizations",
        sa.Column("monthly_revenue_goal", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "monthly_revenue_goal")
    op.drop_index("idx_users_phone_per_org", table_name="users")
    op.drop_column("users", "phone_e164")
