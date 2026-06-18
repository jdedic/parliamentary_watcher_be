"""extend chat_access_keys with limits and chat_eval_records with ip/key tracking

Revision ID: h1i2j3k4l5m6
Revises: g2b3c4d5e6f7
Create Date: 2026-06-18
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'h1i2j3k4l5m6'
down_revision: Union[str, None] = 'g2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chat_access_keys', sa.Column('label', sa.String(100), nullable=True))
    op.add_column('chat_access_keys', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('chat_access_keys', sa.Column('max_requests', sa.Integer(), nullable=True))
    op.add_column('chat_access_keys', sa.Column('requests_used', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('chat_access_keys', sa.Column('max_tokens', sa.Integer(), nullable=True))
    op.add_column('chat_access_keys', sa.Column('tokens_used', sa.Integer(), nullable=False, server_default='0'))

    # Promote the existing seed key to admin so it is never auto-revoked
    op.execute("UPDATE chat_access_keys SET is_admin = true")

    op.add_column('chat_eval_records', sa.Column('ip_address', sa.String(45), nullable=True))
    op.add_column('chat_eval_records', sa.Column('access_key_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_chat_eval_records_access_key_id',
        'chat_eval_records', 'chat_access_keys',
        ['access_key_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_chat_eval_records_access_key_id', 'chat_eval_records', ['access_key_id'])


def downgrade() -> None:
    op.drop_index('ix_chat_eval_records_access_key_id', table_name='chat_eval_records')
    op.drop_constraint('fk_chat_eval_records_access_key_id', 'chat_eval_records', type_='foreignkey')
    op.drop_column('chat_eval_records', 'access_key_id')
    op.drop_column('chat_eval_records', 'ip_address')
    op.drop_column('chat_access_keys', 'tokens_used')
    op.drop_column('chat_access_keys', 'max_tokens')
    op.drop_column('chat_access_keys', 'requests_used')
    op.drop_column('chat_access_keys', 'max_requests')
    op.drop_column('chat_access_keys', 'is_admin')
    op.drop_column('chat_access_keys', 'label')
