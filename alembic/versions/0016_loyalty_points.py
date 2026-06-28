"""fidelidade por pontos — ledger, tiers/regras configuráveis e vouchers

Revision ID: 0016_loyalty_points
Revises: 0015_client_membership_custom
Create Date: 2026-06-27

Fase 2 da fidelidade: introduz PONTOS como moeda única e auditável.

- `loyalty_tiers`  — ladder de níveis configurável por org (substitui a lógica
  fixa de nivel/categoria; o tier do cliente = maior tier com min_points <= saldo).
- `loyalty_rules`  — regra de ganho/resgate por org (pontos por R$, bônus por
  visita, conversão de resgate, validade).
- `loyalty_point_ledger` — APPEND-ONLY: toda mudança de saldo é um lançamento
  (earn/redeem/expire/adjust/reversal) com `balance_after` (CHECK >= 0).
  UNIQUE parcial (org, ref_appointment_id) p/ earn garante idempotência (não
  credita 2x ao reconcluir um atendimento).
- `loyalty_vouchers` — crédito gerado por resgate (consumo no checkout é fase futura).
- `client_loyalty` ganha `points_balance` (saldo materializado) e `current_tier_id`.

Mudança ADITIVA: as colunas `nivel`/`categoria` de `client_loyalty` permanecem
(deprecadas durante a transição) — drop só num cleanup futuro após soak em prod.
Defaults de tiers/regras por org são semeados pelo serviço (lazy) e pelo script
de backfill — não nesta migration.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_loyalty_points"
down_revision = "0015_client_membership_custom"
branch_labels = None
depends_on = None

_NEW_ENUMS = {
    "loyalty_ledger_type": ("earn", "redeem", "expire", "adjust", "reversal"),
    "loyalty_voucher_status": ("ativo", "consumido", "cancelado"),
}

_NEW_TABLES = ("loyalty_tiers", "loyalty_rules", "loyalty_vouchers", "loyalty_point_ledger")


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*_NEW_ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name, labels in _NEW_ENUMS.items():
        postgresql.ENUM(*labels, name=name).create(bind, checkfirst=False)

    # --- tiers (ladder configurável por org) ---
    op.create_table(
        "loyalty_tiers",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("min_points", sa.BigInteger, nullable=False),
        sa.Column("discount_pct", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("perks", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("min_points >= 0", name="loyalty_tiers_min_points_nonneg"),
        sa.CheckConstraint("discount_pct >= 0 AND discount_pct <= 1", name="loyalty_tiers_discount_range"),
        sa.UniqueConstraint("organization_id", "name", name="uq_loyalty_tiers_org_name"),
    )
    op.create_index("idx_loyalty_tiers_org", "loyalty_tiers", ["organization_id", "min_points"])

    # --- regra de pontos por org (1 linha) ---
    op.create_table(
        "loyalty_rules",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("points_per_brl", sa.Numeric(8, 4), nullable=False, server_default=sa.text("1")),
        sa.Column("points_per_visit", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("redemption_brl_per_point", sa.Numeric(8, 4), nullable=False, server_default=sa.text("1")),
        sa.Column("expiration_days", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("points_per_brl >= 0", name="loyalty_rules_ppbrl_nonneg"),
        sa.CheckConstraint("points_per_visit >= 0", name="loyalty_rules_ppvisit_nonneg"),
        sa.CheckConstraint("redemption_brl_per_point >= 0", name="loyalty_rules_redeem_nonneg"),
    )

    # --- vouchers (crédito de resgate) — criado antes do ledger (FK) ---
    op.create_table(
        "loyalty_vouchers",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_brl", sa.Numeric(10, 2), nullable=False),
        sa.Column("points_spent", sa.BigInteger, nullable=False),
        sa.Column("status", _enum("loyalty_voucher_status"), nullable=False, server_default=sa.text("'ativo'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("consumed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "consumed_appointment_id",
            sa.BigInteger,
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("amount_brl >= 0", name="loyalty_vouchers_amount_nonneg"),
        sa.CheckConstraint("points_spent >= 0", name="loyalty_vouchers_points_nonneg"),
    )
    op.create_index("idx_loyalty_vouchers_client", "loyalty_vouchers", ["organization_id", "client_id", "status"])

    # --- ledger append-only ---
    op.create_table(
        "loyalty_point_ledger",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.BigInteger,
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", _enum("loyalty_ledger_type"), nullable=False),
        sa.Column("points_delta", sa.BigInteger, nullable=False),
        sa.Column("balance_after", sa.BigInteger, nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column(
            "ref_appointment_id",
            sa.BigInteger,
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "ref_voucher_id",
            sa.BigInteger,
            sa.ForeignKey("loyalty_vouchers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("balance_after >= 0", name="loyalty_ledger_balance_nonneg"),
    )
    op.create_index(
        "idx_loyalty_ledger_client",
        "loyalty_point_ledger",
        ["organization_id", "client_id", "created_at"],
    )
    # Idempotência: no máximo 1 crédito 'earn' por agendamento.
    op.create_index(
        "uq_loyalty_earn_per_appointment",
        "loyalty_point_ledger",
        ["organization_id", "ref_appointment_id"],
        unique=True,
        postgresql_where=sa.text("type = 'earn' AND ref_appointment_id IS NOT NULL"),
    )

    # --- client_loyalty: saldo materializado + tier atual (aditivo) ---
    op.add_column(
        "client_loyalty",
        sa.Column("points_balance", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "client_loyalty",
        sa.Column(
            "current_tier_id",
            sa.BigInteger,
            sa.ForeignKey("loyalty_tiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- RLS para todas as novas tabelas (client_loyalty já tem do 0002) ---
    for tbl in _NEW_TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tbl} "
            "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_column("client_loyalty", "current_tier_id")
    op.drop_column("client_loyalty", "points_balance")
    for tbl in reversed(_NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
    op.drop_table("loyalty_point_ledger")
    op.drop_table("loyalty_vouchers")
    op.drop_table("loyalty_rules")
    op.drop_table("loyalty_tiers")
    for name in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
