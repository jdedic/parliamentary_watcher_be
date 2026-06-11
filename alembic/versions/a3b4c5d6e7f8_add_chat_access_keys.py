"""add_chat_access_keys

Revision ID: a3b4c5d6e7f8
Revises: e5f6a7b8c9d0
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHAT_ACCESS_GUID = '3f8a2b1c-9d4e-4f7a-b6c5-1e2d3a4b5c6d'


def upgrade() -> None:
    op.create_table(
        'chat_access_keys',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.execute(
        f"INSERT INTO chat_access_keys (key) VALUES ('{CHAT_ACCESS_GUID}')"
    )


def downgrade() -> None:
    op.drop_table('chat_access_keys')
