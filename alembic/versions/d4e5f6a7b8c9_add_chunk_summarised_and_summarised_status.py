"""add_chunk_summarised_and_summarised_status

Revision ID: d4e5f6a7b8c9
Revises: 84cf30ccfa27
Create Date: 2026-03-21 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "84cf30ccfa27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS 'CHUNK_SUMMARISED'")
    op.execute("ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS 'SUMMARISED'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values — requires recreating the type
    pass
