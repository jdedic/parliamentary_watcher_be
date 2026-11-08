"""add speakers table

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-08-15
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "m6n7o8p9q0r1"
down_revision: Union[str, None] = "l5m6n7o8p9q0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "speakers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("function", sa.String(200), nullable=True),
        sa.Column("party_afkorting", sa.String(20), nullable=True),
        sa.Column("party_name_nl", sa.String(200), nullable=True),
        sa.Column("party_name_en", sa.String(200), nullable=True),
        sa.Column("tk_persoon_id", sa.String(36), nullable=True),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "party_afkorting", name="uq_speakers_name_party"),
        sa.UniqueConstraint("tk_persoon_id", name="uq_speakers_tk_persoon_id"),
    )
    op.create_index("ix_speakers_tk_persoon_id", "speakers", ["tk_persoon_id"])


def downgrade() -> None:
    op.drop_index("ix_speakers_tk_persoon_id", table_name="speakers")
    op.drop_table("speakers")
