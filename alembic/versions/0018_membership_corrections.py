"""correções de assinatura — auditoria de cancelamento/estorno + unique parcial de uso

Revision ID: 0018_membership_corrections
Revises: 0017_grant_loyalty_points
Create Date: 2026-06-28

Suporte às ferramentas de correção/reversão da recepcionista (Fase 6 da
auditoria do módulo Assinaturas). Tudo ADITIVO e retrocompatível:

- `client_memberships.canceled_by_user_id` — quem cancelou (auditoria; espelha
  `sold_by_user_id`). NULL para cancelamentos antigos.
- `membership_usages.reverted_by_user_id` — quem estornou o uso (auditoria).
- A unicidade de uso por agendamento passa a considerar SÓ usos ativos
  (`reverted_at IS NULL`): troca a UNIQUE total por um índice único PARCIAL.
  Assim, estornar um uso e (no futuro) re-vincular o mesmo agendamento deixa de
  estourar a constraint; o double-spend concorrente segue barrado (dois usos
  ativos no mesmo agendamento continuam proibidos).

As tabelas já têm RLS + GRANT (0012/0013); `ADD COLUMN`/índice não exigem novo
GRANT. As FKs usam `ondelete=SET NULL` (não travam a remoção do usuário).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_membership_corrections"
down_revision = "0017_grant_loyalty_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── auditoria de quem cancelou a assinatura ──────────────────────────────
    op.add_column(
        "client_memberships",
        sa.Column("canceled_by_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_client_memberships_canceled_by",
        "client_memberships",
        "users",
        ["canceled_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── auditoria de quem estornou o uso ─────────────────────────────────────
    op.add_column(
        "membership_usages",
        sa.Column("reverted_by_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_membership_usages_reverted_by",
        "membership_usages",
        "users",
        ["reverted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── unicidade de uso por agendamento: só usos ATIVOS ─────────────────────
    op.drop_constraint(
        "membership_usages_appt_unique", "membership_usages", type_="unique"
    )
    op.create_index(
        "membership_usages_appt_active_unique",
        "membership_usages",
        ["appointment_id"],
        unique=True,
        postgresql_where=sa.text("reverted_at IS NULL"),
    )


def downgrade() -> None:
    # CAVEAT: recriar a UNIQUE total em appointment_id pode falhar se o recurso de
    # re-vínculo após estorno já tiver gerado um agendamento com >1 linha de uso
    # (uma revertida + uma ativa). É o caveat padrão de downgrade com dados reais;
    # nesse caso, limpar/consolidar os usos revertidos antes de reverter a migration.
    op.drop_index(
        "membership_usages_appt_active_unique", table_name="membership_usages"
    )
    op.create_unique_constraint(
        "membership_usages_appt_unique", "membership_usages", ["appointment_id"]
    )
    op.drop_constraint(
        "fk_membership_usages_reverted_by", "membership_usages", type_="foreignkey"
    )
    op.drop_column("membership_usages", "reverted_by_user_id")
    op.drop_constraint(
        "fk_client_memberships_canceled_by", "client_memberships", type_="foreignkey"
    )
    op.drop_column("client_memberships", "canceled_by_user_id")
