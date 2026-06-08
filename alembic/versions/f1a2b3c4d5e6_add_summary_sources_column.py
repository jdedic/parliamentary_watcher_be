"""add_summary_sources_column

Revision ID: f1a2b3c4d5e6
Revises: 9c37bfc4ad91
Create Date: 2026-05-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '9c37bfc4ad91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('plenary_sessions', sa.Column('summary_sources', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('plenary_sessions', 'summary_sources')
