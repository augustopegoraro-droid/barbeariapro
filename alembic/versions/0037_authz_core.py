"""núcleo de autorização RBAC por permissões (Fase 2)

Revision ID: 0037_authz_core
Revises: 0036_dre_monthly_lines
Create Date: 2026-07-06

Cria o núcleo de autorização baseado em permissões (ARQUITETURA_ALVO.md, Fase 2):
- `permissions`      catálogo GLOBAL (sem RLS; referência lida por todos).
- `roles`            papéis de sistema (organization_id NULL) + personalizados por org.
- `role_permissions` permissões de cada papel.
- `user_roles`       papéis atribuídos a usuários (custom/adicionais).
- `permission_overrides` exceções por usuário (allow/deny).

Isolamento (molde 0036): RLS por `organization_id`. `roles`/`role_permissions`
usam a variante "global OU do tenant" (org NULL = sistema, visível a todos;
WITH CHECK impede o tenant de escrever linhas globais). `user_roles`/
`permission_overrides` são estritamente do tenant.

Somente SCHEMA — o seed do catálogo/papéis de sistema é feito por
`app/services/authz.py::sync_system_catalog` (fonte: `app/core/permissions.py`),
chamado pelo `scripts/seed.py` e `scripts/sync_authz_catalog.py` (idempotente).
FORCE ROW LEVEL SECURITY é deixado para a migration de hardening da Fase 3
(precisa ser aplicado uniformemente + backfill org-aware).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0037_authz_core"
down_revision = "0036_dre_monthly_lines"
branch_labels = None
depends_on = None


_GLOBAL_OR_TENANT = (
    "organization_id IS NULL "
    "OR organization_id = current_setting('app.current_org_id', true)::bigint"
)
_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    # ── permissions (catálogo global, sem RLS) ──────────────────────────────────
    op.create_table(
        "permissions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column(
            "is_sensitive_field",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("GRANT SELECT ON permissions TO barber_app")

    # ── roles (sistema global + personalizados por org) ─────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("color", sa.Text, nullable=True),
        sa.Column("icon", sa.Text, nullable=True),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_assignable", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("organization_id", "slug", name="roles_slug_per_org"),
    )
    op.create_index("idx_roles_org", "roles", ["organization_id"])
    # Unicidade do slug entre papéis de sistema (org NULL): UNIQUE trata NULLs como
    # distintos, então um índice parcial garante 1 papel de sistema por slug.
    op.execute(
        "CREATE UNIQUE INDEX roles_system_slug_unique ON roles (slug) "
        "WHERE organization_id IS NULL"
    )
    op.execute("ALTER TABLE roles ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON roles "
        f"USING ({_GLOBAL_OR_TENANT}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON roles TO barber_app")

    # ── role_permissions ────────────────────────────────────────────────────────
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            sa.BigInteger,
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_id",
            sa.BigInteger,
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "organization_id",
            sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("idx_role_permissions_role", "role_permissions", ["role_id"])
    op.execute("ALTER TABLE role_permissions ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON role_permissions "
        f"USING ({_GLOBAL_OR_TENANT}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON role_permissions TO barber_app"
    )

    # ── user_roles (estritamente do tenant) ─────────────────────────────────────
    op.create_table(
        "user_roles",
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
        sa.Column(
            "role_id",
            sa.BigInteger,
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            sa.BigInteger,
            sa.ForeignKey("units.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "granted_by",
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
        sa.UniqueConstraint("user_id", "role_id", "unit_id", name="user_roles_unique"),
    )
    op.create_index(
        "idx_user_roles_org_user", "user_roles", ["organization_id", "user_id"]
    )
    op.create_index("idx_user_roles_role", "user_roles", ["role_id"])
    op.execute("ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON user_roles "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_roles TO barber_app")

    # ── permission_overrides ────────────────────────────────────────────────────
    op.create_table(
        "permission_overrides",
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
        sa.Column(
            "permission_id",
            sa.BigInteger,
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effect", sa.Text, nullable=False),
        sa.Column(
            "unit_id",
            sa.BigInteger,
            sa.ForeignKey("units.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "granted_by",
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
        sa.CheckConstraint(
            "effect IN ('allow', 'deny')", name="permission_overrides_effect_valid"
        ),
        sa.UniqueConstraint(
            "user_id", "permission_id", "unit_id", name="permission_overrides_unique"
        ),
    )
    op.create_index(
        "idx_permission_overrides_org_user",
        "permission_overrides",
        ["organization_id", "user_id"],
    )
    op.execute("ALTER TABLE permission_overrides ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON permission_overrides "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON permission_overrides TO barber_app"
    )

    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    for tbl in (
        "permission_overrides",
        "user_roles",
        "role_permissions",
        "roles",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
    op.drop_table("permission_overrides")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.execute("DROP INDEX IF EXISTS roles_system_slug_unique")
    op.drop_table("roles")
    op.drop_table("permissions")
