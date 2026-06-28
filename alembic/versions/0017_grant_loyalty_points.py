"""grant CRUD ao barber_app nas tabelas de fidelidade por pontos

Revision ID: 0017_grant_loyalty_points
Revises: 0016_loyalty_points
Create Date: 2026-06-27

A 0016 criou as tabelas + RLS, mas sem GRANT ao role barber_app — sem ele
qualquer leitura/escrita pelo app falha com InsufficientPrivilege antes da RLS
ser avaliada (mesma lição de 0011/0013).
"""
from __future__ import annotations

from alembic import op

revision = "0017_grant_loyalty_points"
down_revision = "0016_loyalty_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE
        ON loyalty_tiers, loyalty_rules, loyalty_vouchers, loyalty_point_ledger
        TO barber_app
    """)
    op.execute("""
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app
    """)


def downgrade() -> None:
    op.execute("""
        REVOKE SELECT, INSERT, UPDATE, DELETE
        ON loyalty_tiers, loyalty_rules, loyalty_vouchers, loyalty_point_ledger
        FROM barber_app
    """)
