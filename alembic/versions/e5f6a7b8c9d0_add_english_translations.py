"""add_english_translations

Revision ID: e5f6a7b8c9d0
Revises: f1a2b3c4d5e6
Create Date: 2026-06-08 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('plenary_sessions', sa.Column('summary_en', sa.Text(), nullable=True))
    op.add_column('plenary_sessions', sa.Column('stances_en', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('plenary_sessions', 'stances_en')
    op.drop_column('plenary_sessions', 'summary_en')
