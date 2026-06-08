"""rename dutch columns to english

Revision ID: a1b2c3d4e5f6
Revises: 948e6fdbdee4
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '948e6fdbdee4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('plenary_sessions', 'soort', new_column_name='kind')
    op.alter_column('plenary_sessions', 'titel', new_column_name='title')
    op.alter_column('plenary_sessions', 'zaal', new_column_name='room')
    op.alter_column('plenary_sessions', 'vergaderjaar', new_column_name='parliamentary_year')
    op.alter_column('plenary_sessions', 'vergadering_nummer', new_column_name='meeting_number')
    op.alter_column('plenary_sessions', 'datum', new_column_name='date')
    op.alter_column('plenary_sessions', 'aanvangstijd', new_column_name='start_time')
    op.alter_column('plenary_sessions', 'sluiting', new_column_name='end_time')
    op.alter_column('plenary_sessions', 'kamer', new_column_name='chamber')
    op.alter_column('plenary_sessions', 'gewijzigd_op', new_column_name='modified_at')
    op.alter_column('plenary_sessions', 'api_gewijzigd_op', new_column_name='api_modified_at')
    op.alter_column('plenary_sessions', 'verwijderd', new_column_name='deleted')


def downgrade() -> None:
    op.alter_column('plenary_sessions', 'kind', new_column_name='soort')
    op.alter_column('plenary_sessions', 'title', new_column_name='titel')
    op.alter_column('plenary_sessions', 'room', new_column_name='zaal')
    op.alter_column('plenary_sessions', 'parliamentary_year', new_column_name='vergaderjaar')
    op.alter_column('plenary_sessions', 'meeting_number', new_column_name='vergadering_nummer')
    op.alter_column('plenary_sessions', 'date', new_column_name='datum')
    op.alter_column('plenary_sessions', 'start_time', new_column_name='aanvangstijd')
    op.alter_column('plenary_sessions', 'end_time', new_column_name='sluiting')
    op.alter_column('plenary_sessions', 'chamber', new_column_name='kamer')
    op.alter_column('plenary_sessions', 'modified_at', new_column_name='gewijzigd_op')
    op.alter_column('plenary_sessions', 'api_modified_at', new_column_name='api_gewijzigd_op')
    op.alter_column('plenary_sessions', 'deleted', new_column_name='verwijderd')
