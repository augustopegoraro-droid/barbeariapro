"""sessões/dispositivos + refresh token + FORCE RLS (Fase 3, D-68)

Revision ID: 0038_sessions_hardening
Revises: 0037_authz_core
Create Date: 2026-07-07

Fecha V9 (JWT sem revogação/refresh — tabela `sessions` é a fonte de verdade de
sessão/refresh token, rotativo com detecção de reuso; Redis só guarda dado
efêmero, ver app/db/redis.py), V11 (parcial — `users.must_change_password`
sustenta o reset administrativo de senha, sem e-mail) e a pendência que o
próprio `0037_authz_core.py` deixou explícita: `FORCE ROW LEVEL SECURITY`.

O FORCE é aplicado DINAMICAMENTE (consulta a `pg_class.relrowsecurity`) em vez
de listar as ~30 tabelas à mão — evita desatualização quando novas tabelas RLS
forem criadas depois desta migration (essas precisarão forçar RLS na própria
migration, este loop só cobre o que já existe hoje). Auditoria (V16/§8)
confirmou `barber_app` é NOBYPASSRLS e não é dono das tabelas, então o efeito
esperado é NO-OP comportamental — só fecha o gap latente de uma futura conexão
como dono/superuser perder a RLS em silêncio.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0038_sessions_hardening"
down_revision = "0037_authz_core"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)

# Tabelas com RLS habilitada mas sem FORCE (estado real em prod, confirmado na
# auditoria §8). `sessions` (criada nesta mesma migration) entra também.
_FORCE_RLS_QUERY = sa.text(
    """
    SELECT relname FROM pg_class
    WHERE relnamespace = 'public'::regnamespace
      AND relkind = 'r'
      AND relrowsecurity = true
      AND relforcerowsecurity = false
    """
)
_UNFORCE_RLS_QUERY = sa.text(
    """
    SELECT relname FROM pg_class
    WHERE relnamespace = 'public'::regnamespace
      AND relkind = 'r'
      AND relrowsecurity = true
      AND relforcerowsecurity = true
    """
)


def upgrade() -> None:
    # ── users.must_change_password (reset administrativo de senha, D-68) ───────
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ── sessions (dispositivos + refresh token rotativo) ────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_token_hash", sa.Text, nullable=False),
        sa.Column("prev_refresh_token_hash", sa.Text, nullable=True),
        sa.Column("jti_current", sa.Text, nullable=False),
        sa.Column("device_label", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("os", sa.Text, nullable=True),
        sa.Column("browser", sa.Text, nullable=True),
        sa.Column("ip", sa.Text, nullable=True),
        # Reservado p/ geolocalização por IP — fora do MVP (ver docstring). Nunca
        # preenchido hoje; existe só para não exigir migration nova depois.
        sa.Column("ip_geo", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("refresh_expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "revoked_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_sessions_user_revoked", "sessions", ["user_id", "revoked_at"])
    op.create_index(
        "idx_sessions_refresh_hash", "sessions", ["refresh_token_hash"], unique=True
    )
    op.execute("ALTER TABLE sessions ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON sessions "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON sessions TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")

    # ── resolução pré-tenant do refresh token (molde 0020) ──────────────────────
    # `POST /auth/refresh` recebe só o refresh token — não sabe a org ainda, e
    # `sessions` tem RLS. Casa contra o hash ATUAL e o ANTERIOR (janela de reuso
    # pós-rotação) e devolve só o organization_id (ignora a RLS via SECURITY
    # DEFINER, molde app_org_id_by_subdomain/app_org_id_by_wa_instance).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_org_id_by_refresh_hash(p_hash text)
        RETURNS bigint
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT organization_id FROM sessions
            WHERE (refresh_token_hash = p_hash OR prev_refresh_token_hash = p_hash)
              AND revoked_at IS NULL
            LIMIT 1
        $$
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_org_id_by_refresh_hash(text) TO barber_app"
    )

    # ── FORCE ROW LEVEL SECURITY (hardening, V16) ───────────────────────────────
    # Dinâmico: pega TODAS as tabelas com RLS ativa e sem FORCE (inclui `sessions`,
    # recém-criada acima, e as ~30 tabelas de tenant já existentes).
    bind = op.get_bind()
    tables = [row[0] for row in bind.execute(_FORCE_RLS_QUERY)]
    for tbl in tables:
        op.execute(f'ALTER TABLE "{tbl}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    bind = op.get_bind()
    tables = [row[0] for row in bind.execute(_UNFORCE_RLS_QUERY)]
    for tbl in tables:
        op.execute(f'ALTER TABLE "{tbl}" NO FORCE ROW LEVEL SECURITY')

    op.execute("DROP FUNCTION IF EXISTS app_org_id_by_refresh_hash(text)")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sessions")
    op.execute("ALTER TABLE sessions DISABLE ROW LEVEL SECURITY")
    op.drop_table("sessions")

    op.drop_column("users", "must_change_password")
