"""crm — leads (funil/Kanban) + lead_events + enum lead_stage

Revision ID: 0007_crm_leads
Revises: 0006_client_blocked
Create Date: 2026-06-16

Aditiva: cria apenas tabelas/enum novos e suas policies de RLS. Não altera
nenhuma tabela existente.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_crm_leads"
down_revision: Union[str, None] = "0006_client_blocked"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEAD_STAGE = ("novo_contato", "conversando", "agendado", "concluido", "perdido")


def _lead_stage() -> postgresql.ENUM:
    return postgresql.ENUM(*_LEAD_STAGE, name="lead_stage", create_type=False)


def _contact_channel() -> postgresql.ENUM:
    # Tipo já existente no banco — apenas referenciar, nunca recriar.
    return postgresql.ENUM(name="contact_channel", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(*_LEAD_STAGE, name="lead_stage").create(bind, checkfirst=False)

    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            sa.BigInteger,
            sa.ForeignKey("units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "client_id",
            sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("phone_e164", sa.Text, nullable=True),
        sa.Column("source", _contact_channel(), nullable=True),
        sa.Column(
            "stage",
            _lead_stage(),
            nullable=False,
            server_default=sa.text("'novo_contato'"),
        ),
        sa.Column("position", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "assigned_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_contact_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_leads_org_stage", "leads", ["organization_id", "stage"])
    op.create_index(
        "idx_leads_org_position", "leads", ["organization_id", "stage", "position"]
    )
    op.create_index("idx_leads_client", "leads", ["client_id"])

    op.create_table(
        "lead_events",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "lead_id",
            sa.BigInteger,
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("from_stage", _lead_stage(), nullable=True),
        sa.Column("to_stage", _lead_stage(), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_lead_events_lead", "lead_events", ["lead_id"])
    op.create_index(
        "idx_lead_events_org_created", "lead_events", ["organization_id", "created_at"]
    )

    # RLS — isolamento por organização (mesmo padrão das demais tabelas tenant)
    for tbl in ("leads", "lead_events"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tbl} "
            "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
        )


def downgrade() -> None:
    bind = op.get_bind()

    for tbl in ("lead_events", "leads"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")

    op.drop_table("lead_events")
    op.drop_table("leads")

    postgresql.ENUM(name="lead_stage").drop(bind, checkfirst=False)
