"""foto do cliente final (Fase A do app nativo): clients.photo_path

Revision ID: 0059_client_photo
Revises: 0058_appointment_ratings
Create Date: 2026-08-21

Molde literal de `0045_barber_photo.py`: guarda o **caminho relativo** do
arquivo no storage de mídia (ex.: `org1/client-<uuid>.webp?v=1769...`), nunca a
URL completa — a URL pública é montada na leitura a partir de
`MEDIA_PUBLIC_BASE`.

Não reaproveita `clients.last_photo_url` de propósito: aquele campo é da foto
recebida pelo bot/importada da Trinks (outra semântica, outra origem).

Sem RLS/GRANT novo: a coluna entra numa tabela que já tem os dois (`clients`).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0059_client_photo"
down_revision = "0058_appointment_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("photo_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "photo_path")
