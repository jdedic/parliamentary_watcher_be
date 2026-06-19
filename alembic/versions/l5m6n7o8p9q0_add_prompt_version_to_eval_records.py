"""add prompt_version column to chat_eval_records

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-06-19
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "l5m6n7o8p9q0"
down_revision: Union[str, None] = "k4l5m6n7o8p9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_eval_records",
        sa.Column("prompt_version", sa.String(120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_eval_records", "prompt_version")
