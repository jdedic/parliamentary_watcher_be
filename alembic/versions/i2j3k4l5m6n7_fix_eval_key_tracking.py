"""drop access_key FK (use plain int) and add key_label to preserve tracking after key revocation

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-06-18
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'i2j3k4l5m6n7'
down_revision: Union[str, None] = 'h1i2j3k4l5m6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('fk_chat_eval_records_access_key_id', 'chat_eval_records', type_='foreignkey')
    op.add_column('chat_eval_records', sa.Column('key_label', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_eval_records', 'key_label')
    op.create_foreign_key(
        'fk_chat_eval_records_access_key_id',
        'chat_eval_records', 'chat_access_keys',
        ['access_key_id'], ['id'],
        ondelete='SET NULL',
    )
