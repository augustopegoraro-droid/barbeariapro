"""add last_photo_url to clients

Revision ID: 0002_client_last_photo
Revises: 0001_initial
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0002_client_last_photo"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("last_photo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "last_photo_url")
