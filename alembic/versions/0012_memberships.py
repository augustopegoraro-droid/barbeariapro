"""mensalidade/assinatura do cliente final — membership_plans + items +
client_memberships + membership_usages (+ enum membership_status)

Revision ID: 0012_memberships
Revises: 0011_grant_crm_tables
Create Date: 2026-06-26

Aditiva: cria tabelas/enum novos para a mensalidade do CLIENTE FINAL (combo
fixo + N usos, receita rateada no uso). NÃO altera appointments, payments,
clients, services nem o Plan/Subscription do tenant SaaS. O GRANT ao role
barber_app é feito na migration seguinte (0013), espelhando 0010/0011.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_memberships"
down_revision: Union[str, None] = "0011_grant_crm_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MEMBERSHIP_STATUS = ("ativa", "vencida", "cancelada")


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(*_MEMBERSHIP_STATUS, name="membership_status").create(
        bind, checkfirst=False
    )

    # ── membership_plans (catálogo: combo fixo + N usos) ────────────────────
    op.create_table(
        "membership_plans",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger,
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("included_uses", sa.Integer, nullable=True),  # NULL = ilimitado
        sa.Column("duration_days", sa.Integer, nullable=False),
        sa.Column("unlimited_use_value", sa.Numeric(10, 2), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("price >= 0", name="membership_plans_price_nonneg"),
        sa.CheckConstraint("included_uses IS NULL OR included_uses > 0",
                           name="membership_plans_uses_pos"),
        sa.CheckConstraint("duration_days > 0", name="membership_plans_duration_pos"),
        sa.CheckConstraint("unlimited_use_value IS NULL OR unlimited_use_value >= 0",
                           name="membership_plans_unit_value_nonneg"),
    )
    op.create_index("idx_membership_plans_org", "membership_plans", ["organization_id"])

    # ── membership_plan_items (composição do combo) ─────────────────────────
    op.create_table(
        "membership_plan_items",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger,
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", sa.BigInteger,
                  sa.ForeignKey("membership_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.BigInteger,
                  sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("position", sa.SmallInteger, nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("plan_id", "service_id", name="membership_plan_item_unique"),
    )
    op.create_index("idx_membership_plan_items_plan", "membership_plan_items", ["plan_id"])

    # ── client_memberships (assinatura contratada, com snapshots) ───────────
    op.create_table(
        "client_memberships",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", sa.Uuid, nullable=False, unique=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.BigInteger,
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.BigInteger,
                  sa.ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", sa.BigInteger,
                  sa.ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", _enum("membership_status"), nullable=False,
                  server_default=sa.text("'ativa'")),
        sa.Column("start_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("price_paid", sa.Numeric(10, 2), nullable=False),
        sa.Column("included_uses", sa.Integer, nullable=True),
        sa.Column("used_uses", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("unit_recognized_value", sa.Numeric(10, 2), nullable=False),
        sa.Column("combo_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("duration_days", sa.Integer, nullable=False),
        sa.Column("sold_by_user_id", sa.BigInteger,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("canceled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("end_at > start_at", name="client_memberships_period_valid"),
        sa.CheckConstraint("price_paid >= 0", name="client_memberships_price_nonneg"),
        sa.CheckConstraint("used_uses >= 0", name="client_memberships_used_nonneg"),
        sa.CheckConstraint("included_uses IS NULL OR used_uses <= included_uses",
                           name="client_memberships_used_within_limit"),
    )
    op.create_index("idx_client_memberships_client", "client_memberships", ["client_id"])
    op.create_index("idx_client_memberships_org_status", "client_memberships",
                    ["organization_id", "status"])
    op.create_index("idx_client_memberships_active", "client_memberships",
                    ["organization_id", "client_id"],
                    postgresql_where=sa.text("status = 'ativa'"))

    # ── membership_usages (histórico + vínculo 1:1 ao appointment) ──────────
    op.create_table(
        "membership_usages",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger,
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("membership_id", sa.BigInteger,
                  sa.ForeignKey("client_memberships.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("appointment_id", sa.BigInteger,
                  sa.ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recognized_value", sa.Numeric(10, 2), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("reverted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("recognized_value >= 0", name="membership_usages_value_nonneg"),
        sa.UniqueConstraint("appointment_id", name="membership_usages_appt_unique"),
    )
    op.create_index("idx_membership_usages_membership", "membership_usages",
                    ["membership_id"])

    # ── RLS — mesmo padrão das demais tabelas tenant ───────────────────────
    for tbl in ("membership_plans", "membership_plan_items",
                "client_memberships", "membership_usages"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tbl} "
            "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    for tbl in ("membership_usages", "client_memberships",
                "membership_plan_items", "membership_plans"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
    op.drop_table("membership_usages")
    op.drop_table("client_memberships")
    op.drop_table("membership_plan_items")
    op.drop_table("membership_plans")
    postgresql.ENUM(name="membership_status").drop(bind, checkfirst=False)
