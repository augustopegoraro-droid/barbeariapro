"""foto do profissional (D-85): barbers.photo_path

Revision ID: 0045_barber_photo
Revises: 0044_public_site
Create Date: 2026-07-29

Aditiva e reversível. Guarda o **caminho relativo** do arquivo no storage de
mídia (ex.: `org1/barber-7.webp?v=1769...`), nunca a URL completa: a URL pública
é montada na leitura a partir de `MEDIA_PUBLIC_BASE`, então trocar de domínio
(ou de storage) não invalida o que está no banco.

Sem RLS/GRANT novo: a coluna entra numa tabela que já tem os dois (`barbers`).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0045_barber_photo"
down_revision = "0044_public_site"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("barbers", sa.Column("photo_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("barbers", "photo_path")
