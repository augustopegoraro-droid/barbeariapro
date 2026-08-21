"""Feed de novidades/promoções — mural que o gestor publica e o cliente final lê
no site público.

Molde de `appointment_ratings`/0058 (RLS + `FORCE ROW LEVEL SECURITY` + GRANT
explícito ao `barber_app`), com uma diferença deliberada: o GRANT inclui
`UPDATE` (o post é editável e arquivável) mas **nunca `DELETE`** — arquivar é
`deleted_at`, mesmo padrão de `services`/`barbers`.

`public_id` (uuid, `gen_random_uuid()` — mesmo default de `clients`/`appointments`
desde a 0001) é o identificador exposto na vitrine; o id sequencial fica no
painel.

Revision ID: 0061_feed_posts
Revises: 0060_push_native_channel
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0061_feed_posts"
down_revision = "0060_push_native_channel"
branch_labels = None
depends_on = None

_TENANT_ONLY = (
    "organization_id = current_setting('app.current_org_id', true)::bigint"
)


def upgrade() -> None:
    op.create_table(
        "feed_posts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "organization_id", sa.BigInteger,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "public_id", sa.Uuid, nullable=False, unique=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("image_path", sa.Text, nullable=True),
        sa.Column(
            "is_published", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "published_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_user_id", sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 2 AND 120", name="feed_posts_title_len"
        ),
        sa.CheckConstraint("char_length(body) <= 2000", name="feed_posts_body_len"),
    )
    # A rota pública filtra por org + publicado e ordena por data desc.
    op.execute(
        "CREATE INDEX idx_feed_posts_org_published ON feed_posts "
        "(organization_id, is_published, published_at DESC)"
    )

    op.execute("ALTER TABLE feed_posts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON feed_posts "
        f"USING ({_TENANT_ONLY}) WITH CHECK ({_TENANT_ONLY})"
    )
    op.execute("ALTER TABLE feed_posts FORCE ROW LEVEL SECURITY")
    # Sem DELETE de propósito: arquivar é `deleted_at`.
    op.execute("GRANT SELECT, INSERT, UPDATE ON feed_posts TO barber_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO barber_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON feed_posts")
    op.execute("ALTER TABLE feed_posts DISABLE ROW LEVEL SECURITY")
    op.drop_table("feed_posts")
