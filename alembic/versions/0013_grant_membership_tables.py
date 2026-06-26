"""grant permissões de CRUD ao barber_app nas tabelas de mensalidade

Revision ID: 0013_grant_membership_tables
Revises: 0012_memberships
Create Date: 2026-06-26

A migration 0012 criou as tabelas de mensalidade + RLS, mas (como o 0010) não
concede GRANT ao role barber_app. Sem ele, qualquer escrita/leitura pelo app
falha com InsufficientPrivilege antes da RLS ser avaliada (lição do 0011).
"""
from __future__ import annotations

from alembic import op

revision = "0013_grant_membership_tables"
down_revision = "0012_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE
        ON membership_plans, membership_plan_items,
           client_memberships, membership_usages
        TO barber_app
    """)
    # Sequences Identity das novas tabelas só existem após a 0012.
    op.execute("""
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app
    """)


def downgrade() -> None:
    op.execute("""
        REVOKE SELECT, INSERT, UPDATE, DELETE
        ON membership_plans, membership_plan_items,
           client_memberships, membership_usages
        FROM barber_app
    """)
