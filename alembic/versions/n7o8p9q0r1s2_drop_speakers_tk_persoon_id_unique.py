"""drop unique constraint on speakers.tk_persoon_id

The same real Tweede Kamer person can legitimately be represented by more than
one `speakers` row (different free-text name spellings/orderings across
sessions all resolving to the same tk_persoon_id), so this must not be unique.
The plain index (ix_speakers_tk_persoon_id) is kept for lookup speed.

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-08-15
"""
from typing import Union

from alembic import op

revision: str = "n7o8p9q0r1s2"
down_revision: Union[str, None] = "m6n7o8p9q0r1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_speakers_tk_persoon_id", "speakers", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_speakers_tk_persoon_id", "speakers", ["tk_persoon_id"])
