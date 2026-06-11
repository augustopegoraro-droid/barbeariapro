"""loyalty module — client_loyalty table + enums

Revision ID: 0002_loyalty
Revises: 0001_initial
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_loyalty"
down_revision: Union[str, None] = "0003_client_photo_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_ENUMS = {
    "loyalty_nivel": ("novo", "ativo", "fiel", "vip"),
    "loyalty_status": ("ativo", "em_risco", "inativo"),
    "loyalty_categoria": ("bronze", "prata", "ouro", "diamante"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*_NEW_ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    for name, labels in _NEW_ENUMS.items():
        postgresql.ENUM(*labels, name=name).create(bind, checkfirst=False)

    op.create_table(
        "client_loyalty",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "client_id",
            sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("visit_count", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "total_spent",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_visit_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "nivel",
            _enum("loyalty_nivel"),
            nullable=False,
            server_default=sa.text("'novo'"),
        ),
        sa.Column(
            "status",
            _enum("loyalty_status"),
            nullable=False,
            server_default=sa.text("'ativo'"),
        ),
        sa.Column("categoria", _enum("loyalty_categoria"), nullable=True),
        sa.Column(
            "preferred_barber_id",
            sa.BigInteger,
            sa.ForeignKey("barbers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "preferred_service_id",
            sa.BigInteger,
            sa.ForeignKey("services.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index("idx_client_loyalty_org_nivel", "client_loyalty", ["organization_id", "nivel"])
    op.create_index("idx_client_loyalty_org_status", "client_loyalty", ["organization_id", "status"])

    # RLS — isolamento por organização
    op.execute("ALTER TABLE client_loyalty ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON client_loyalty "
        "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON client_loyalty")
    op.execute("ALTER TABLE client_loyalty DISABLE ROW LEVEL SECURITY")
    op.drop_table("client_loyalty")

    for name in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
