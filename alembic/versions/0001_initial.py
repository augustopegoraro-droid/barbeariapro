"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-30

Cria toda a estrutura do banco do MVP BarbeariaPro:
ENUMs -> tabelas (ordem de dependência) -> índices -> RLS.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Definição dos ENUMs (espelham os tipos do schema aprovado)
# ---------------------------------------------------------------------------
ENUMS: dict[str, tuple[str, ...]] = {
    "subscription_status": ("trial", "active", "past_due", "canceled"),
    "unit_role": ("owner", "manager", "reception", "barber"),
    "service_category": ("cabelo", "barba", "combo", "quimica", "estetica"),
    "contact_channel": ("whatsapp", "instagram", "google", "indicacao", "passante"),
    "appointment_status": ("agendado", "concluido", "cancelado", "faltou"),
    "payment_method": ("dinheiro", "cartao", "pix"),
    "consent_status": ("opt_in", "opt_out"),
    "integration_provider": ("google_calendar", "whatsapp"),
    "integration_status": ("active", "revoked", "error"),
    "sync_status": ("pending", "synced", "failed"),
    "message_direction": ("outbound", "inbound"),
    "delivery_status": ("pending", "sent", "delivered", "failed"),
}

# Tabelas que recebem Row-Level Security (filtro por organização).
RLS_TABLES_ORG = [
    "subscriptions", "units", "users", "barbers", "services", "clients",
    "appointments", "payments", "expense_categories", "expenses",
    "integration_accounts", "message_log",
]


def _enum(name: str) -> postgresql.ENUM:
    """Referência a um ENUM já existente (não recria o tipo)."""
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    # -- ENUMs --------------------------------------------------------------
    for name, labels in ENUMS.items():
        postgresql.ENUM(*labels, name=name).create(bind, checkfirst=False)

    # -- plans --------------------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("price_month", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("max_units", sa.Integer, nullable=False),
        sa.Column("max_barbers", sa.Integer, nullable=False),
        sa.Column("features", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("price_month >= 0", name="plans_price_nonneg"),
        sa.CheckConstraint("max_units > 0", name="plans_units_positive"),
        sa.CheckConstraint("max_barbers > 0", name="plans_barbers_pos"),
    )

    # -- organizations ------------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # -- subscriptions ------------------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", _enum("subscription_status"), nullable=False, server_default=sa.text("'trial'")),
        sa.Column("current_period_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("canceled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("current_period_end > current_period_start", name="subs_period_valid"),
    )
    op.create_index("idx_subscriptions_org", "subscriptions", ["organization_id"])
    op.create_index("idx_subscriptions_status", "subscriptions", ["status"])

    # -- units --------------------------------------------------------------
    op.create_table(
        "units",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("timezone", sa.Text, nullable=False, server_default=sa.text("'America/Sao_Paulo'")),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("idx_units_org", "units", ["organization_id"])

    # -- users --------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "email", name="users_email_per_org"),
    )

    # -- barbers ------------------------------------------------------------
    op.create_table(
        "barbers",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("specialty", sa.Text, nullable=True),
        sa.Column("commission_pct", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("commission_pct >= 0 AND commission_pct <= 1", name="barbers_commission_range"),
    )
    op.create_index("idx_barbers_org", "barbers", ["organization_id"])

    # -- user_units ---------------------------------------------------------
    op.create_table(
        "user_units",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit_id", sa.BigInteger, sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", _enum("unit_role"), nullable=False),
        sa.Column("barber_id", sa.BigInteger, sa.ForeignKey("barbers.id", ondelete="SET NULL"), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "unit_id"),
    )
    op.create_index("idx_user_units_unit", "user_units", ["unit_id"])
    op.create_index("idx_user_units_barber", "user_units", ["barber_id"])

    # -- barber_units -------------------------------------------------------
    op.create_table(
        "barber_units",
        sa.Column("barber_id", sa.BigInteger, sa.ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit_id", sa.BigInteger, sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("barber_id", "unit_id"),
    )
    op.create_index("idx_barber_units_unit", "barber_units", ["unit_id"])

    # -- services -----------------------------------------------------------
    op.create_table(
        "services",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("category", _enum("service_category"), nullable=False),
        sa.Column("default_duration_min", sa.Integer, nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("cost", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("default_duration_min > 0", name="services_duration_pos"),
        sa.CheckConstraint("price >= 0", name="services_price_nonneg"),
        sa.CheckConstraint("cost >= 0", name="services_cost_nonneg"),
    )
    op.create_index("idx_services_org", "services", ["organization_id"])

    # -- clients ------------------------------------------------------------
    op.create_table(
        "clients",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("phone_e164", sa.Text, nullable=False),
        sa.Column("acquisition_channel", _enum("contact_channel"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "phone_e164", name="clients_phone_per_org"),
        sa.CheckConstraint(r"phone_e164 ~ '^\+[1-9][0-9]{7,14}$'", name="clients_phone_e164_fmt"),
    )

    # -- client_consents ----------------------------------------------------
    op.create_table(
        "client_consents",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("client_id", sa.BigInteger, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", _enum("contact_channel"), nullable=False),
        sa.Column("status", _enum("consent_status"), nullable=False),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("client_id", "channel", name="client_consents_unique"),
    )
    op.create_index("idx_client_consents_client", "client_consents", ["client_id"])

    # -- appointments -------------------------------------------------------
    op.create_table(
        "appointments",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_id", sa.BigInteger, sa.ForeignKey("units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.BigInteger, sa.ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("display_number", sa.Integer, nullable=False),
        sa.Column("start_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", _enum("appointment_status"), nullable=False, server_default=sa.text("'agendado'")),
        sa.Column("booking_channel", _enum("contact_channel"), nullable=True),
        sa.Column("rating", sa.SmallInteger, nullable=True),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("end_at > start_at", name="appt_time_valid"),
        sa.CheckConstraint("rating IS NULL OR (rating BETWEEN 1 AND 5)", name="appt_rating_range"),
        sa.CheckConstraint("total_amount >= 0", name="appt_total_nonneg"),
        sa.UniqueConstraint("unit_id", "display_number", name="appt_display_per_unit"),
    )
    op.create_index("idx_appt_org_start", "appointments", ["organization_id", "start_at"])
    op.create_index("idx_appt_unit_start", "appointments", ["unit_id", "start_at"])
    op.create_index("idx_appt_client_start", "appointments", ["client_id", "start_at"])
    op.create_index("idx_appt_unit_status_start", "appointments", ["unit_id", "status", "start_at"])

    # -- appointment_items --------------------------------------------------
    op.create_table(
        "appointment_items",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("appointment_id", sa.BigInteger, sa.ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.BigInteger, sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("barber_id", sa.BigInteger, sa.ForeignKey("barbers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("price_charged", sa.Numeric(10, 2), nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("position", sa.SmallInteger, nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("price_charged >= 0", name="appt_items_price_nonneg"),
        sa.CheckConstraint("duration_minutes > 0", name="appt_items_dur_pos"),
    )
    op.create_index("idx_appt_items_appt", "appointment_items", ["appointment_id"])
    op.create_index("idx_appt_items_barber", "appointment_items", ["barber_id"])
    op.create_index("idx_appt_items_service", "appointment_items", ["service_id"])

    # -- payments -----------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("appointment_id", sa.BigInteger, sa.ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("tip_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("method", _enum("payment_method"), nullable=False),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount >= 0", name="payments_amount_nonneg"),
        sa.CheckConstraint("tip_amount IS NULL OR tip_amount >= 0", name="payments_tip_nonneg"),
    )
    op.create_index("idx_payments_appt", "payments", ["appointment_id"])
    op.create_index("idx_payments_org_paid", "payments", ["organization_id", "paid_at"])

    # -- expense_categories -------------------------------------------------
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="expense_cat_unique"),
    )

    # -- expenses -----------------------------------------------------------
    op.create_table(
        "expenses",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_id", sa.BigInteger, sa.ForeignKey("units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category_id", sa.BigInteger, sa.ForeignKey("expense_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("competence_month", sa.Date, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount >= 0", name="expenses_amount_nonneg"),
        sa.CheckConstraint("EXTRACT(DAY FROM competence_month) = 1", name="expenses_competence_first_day"),
    )
    op.create_index("idx_expenses_org_month", "expenses", ["organization_id", "competence_month"])
    op.create_index("idx_expenses_unit", "expenses", ["unit_id"])

    # -- business_hours -----------------------------------------------------
    op.create_table(
        "business_hours",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("unit_id", sa.BigInteger, sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.SmallInteger, nullable=False),
        sa.Column("open_time", sa.Time, nullable=False),
        sa.Column("close_time", sa.Time, nullable=False),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="bh_weekday_range"),
        sa.CheckConstraint("close_time > open_time", name="bh_time_valid"),
        sa.UniqueConstraint("unit_id", "weekday", "open_time", name="bh_unique_slot"),
    )
    op.create_index("idx_business_hours_unit", "business_hours", ["unit_id"])

    # -- time_off -----------------------------------------------------------
    op.create_table(
        "time_off",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("barber_id", sa.BigInteger, sa.ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.CheckConstraint("end_at > start_at", name="time_off_valid"),
    )
    op.create_index("idx_time_off_barber", "time_off", ["barber_id", "start_at"])

    # -- integration_accounts ----------------------------------------------
    op.create_table(
        "integration_accounts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_id", sa.BigInteger, sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=True),
        sa.Column("provider", _enum("integration_provider"), nullable=False),
        sa.Column("token_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("refresh_token_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("status", _enum("integration_status"), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_integration_accounts_org", "integration_accounts", ["organization_id"])
    op.create_index("idx_integration_accounts_provider", "integration_accounts", ["organization_id", "provider"])

    # -- calendar_sync ------------------------------------------------------
    op.create_table(
        "calendar_sync",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("appointment_id", sa.BigInteger, sa.ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_account_id", sa.BigInteger, sa.ForeignKey("integration_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_event_id", sa.Text, nullable=True),
        sa.Column("external_etag", sa.Text, nullable=True),
        sa.Column("sync_status", _enum("sync_status"), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("appointment_id", "integration_account_id", name="calendar_sync_unique"),
        sa.CheckConstraint("attempt_count >= 0", name="calendar_sync_attempts_nonneg"),
    )
    op.create_index(
        "idx_calendar_sync_pending", "calendar_sync", ["sync_status"],
        postgresql_where=sa.text("sync_status IN ('pending', 'failed')"),
    )
    op.create_index(
        "idx_calendar_sync_event", "calendar_sync", ["external_event_id"],
        postgresql_where=sa.text("external_event_id IS NOT NULL"),
    )

    # -- message_log --------------------------------------------------------
    op.create_table(
        "message_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("organization_id", sa.BigInteger, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.BigInteger, sa.ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("appointment_id", sa.BigInteger, sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("direction", _enum("message_direction"), nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=True, unique=True),
        sa.Column("template", sa.Text, nullable=True),
        sa.Column("delivery_status", _enum("delivery_status"), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("attempt_count >= 0", name="message_log_attempts_nonneg"),
    )
    op.create_index("idx_message_log_org_created", "message_log", ["organization_id", "created_at"])
    op.create_index("idx_message_log_client", "message_log", ["client_id"])
    op.create_index(
        "idx_message_log_retry", "message_log", ["next_retry_at"],
        postgresql_where=sa.text("delivery_status IN ('pending', 'failed') AND next_retry_at IS NOT NULL"),
    )

    # -- Row-Level Security (isolamento por organização) --------------------
    # A aplicação define o tenant da sessão: SET app.current_org_id = '<id>'.
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY org_isolation ON organizations "
        "USING (id = current_setting('app.current_org_id', true)::bigint)"
    )
    for tbl in RLS_TABLES_ORG:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tbl} "
            "USING (organization_id = current_setting('app.current_org_id', true)::bigint)"
        )


def downgrade() -> None:
    bind = op.get_bind()

    # -- RLS (remover policies antes de derrubar as tabelas) ----------------
    for tbl in RLS_TABLES_ORG:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS org_isolation ON organizations")
    op.execute("ALTER TABLE organizations DISABLE ROW LEVEL SECURITY")

    # -- Tabelas (ordem inversa de dependência) -----------------------------
    op.drop_table("message_log")
    op.drop_table("calendar_sync")
    op.drop_table("integration_accounts")
    op.drop_table("time_off")
    op.drop_table("business_hours")
    op.drop_table("expenses")
    op.drop_table("expense_categories")
    op.drop_table("payments")
    op.drop_table("appointment_items")
    op.drop_table("appointments")
    op.drop_table("client_consents")
    op.drop_table("clients")
    op.drop_table("services")
    op.drop_table("barber_units")
    op.drop_table("user_units")
    op.drop_table("barbers")
    op.drop_table("users")
    op.drop_table("units")
    op.drop_table("subscriptions")
    op.drop_table("organizations")
    op.drop_table("plans")

    # -- ENUMs --------------------------------------------------------------
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
