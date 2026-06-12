"""add chat_eval_records table

Revision ID: g2b3c4d5e6f7
Revises: a3b4c5d6e7f8
Create Date: 2026-06-12
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'g2b3c4d5e6f7'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chat_eval_records',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('question_id', sa.String(8), nullable=False),
        sa.Column('run_id', sa.String(100), nullable=False),
        sa.Column('session_id', sa.String(36), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('retrieval_confidence', sa.String(50), nullable=False),
        sa.Column('generation_confidence', sa.String(50), nullable=True),
        sa.Column('judge_verdict', sa.String(20), nullable=False),
        sa.Column('judge_grounded', sa.Boolean(), nullable=True),
        sa.Column('judge_answers_question', sa.Boolean(), nullable=True),
        sa.Column('judge_missing_context', sa.Boolean(), nullable=True),
        sa.Column('judge_missing_parts', JSONB(), nullable=False, server_default='[]'),
        sa.Column('judge_unsupported_claims', JSONB(), nullable=False, server_default='[]'),
        sa.Column('judge_entity_errors', JSONB(), nullable=False, server_default='[]'),
        sa.Column('judge_reason', sa.Text(), nullable=True),
        sa.Column('context_chunk_ids', JSONB(), nullable=False, server_default='[]'),
        sa.Column('retrieved_chunk_ids', JSONB(), nullable=False, server_default='[]'),
        sa.Column('matched_speakers', JSONB(), nullable=False, server_default='[]'),
        sa.Column('regenerated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('model', sa.String(50), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('cost_estimate_usd', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )
    op.create_index('ix_chat_eval_records_question_id', 'chat_eval_records', ['question_id'], unique=True)
    op.create_index('ix_chat_eval_records_run_id', 'chat_eval_records', ['run_id'])
    op.create_index('ix_chat_eval_records_session_id', 'chat_eval_records', ['session_id'])
    op.create_index('ix_chat_eval_records_judge_verdict', 'chat_eval_records', ['judge_verdict'])


def downgrade() -> None:
    op.drop_table('chat_eval_records')
