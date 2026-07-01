"""clientes: campos vindos da migração da Trinks (e-mail, nascimento, observações)

Revision ID: 0022_client_trinks_fields
Revises: 0021_platform_superadmin
Create Date: 2026-07-01

Onboarding de clientes migrados da Trinks (D-56/import). O modelo `Client` era
enxuto (só nome + telefone + canal); o export da Trinks traz dados valiosos para
CRM/marketing que não tinham onde ir. Tudo ADITIVO e retrocompatível (colunas
nullable; nenhum fluxo existente muda):

- `clients.email` — e-mail do cliente (opcional; base para marketing/aniversário).
- `clients.birth_date` — data de nascimento (campanhas de aniversário).
- `clients.notes` — observações livres (importadas da Trinks: obs + Instagram +
  origem, quando presentes).

NÃO importamos CPF (PII sensível, sem uso no produto hoje — LGPD: minimizar dado).

`clients` já tem RLS + GRANT; `ADD COLUMN` não exige novo GRANT.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0022_client_trinks_fields"
down_revision = "0021_platform_superadmin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("clients", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "notes")
    op.drop_column("clients", "birth_date")
    op.drop_column("clients", "email")
