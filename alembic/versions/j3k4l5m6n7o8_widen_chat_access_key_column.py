"""widen chat_access_keys.key column from 36 to 64 chars for urlsafe tokens

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-06-18
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "j3k4l5m6n7o8"
down_revision: Union[str, None] = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "chat_access_keys",
        "key",
        existing_type=sa.String(36),
        type_=sa.String(64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "chat_access_keys",
        "key",
        existing_type=sa.String(64),
        type_=sa.String(36),
        existing_nullable=False,
    )
