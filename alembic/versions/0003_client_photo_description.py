"""add last_photo_description to clients

Revision ID: 0003_client_photo_description
Revises: 0002_client_last_photo
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0003_client_photo_description"
down_revision = "0002_client_last_photo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("last_photo_description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "last_photo_description")
