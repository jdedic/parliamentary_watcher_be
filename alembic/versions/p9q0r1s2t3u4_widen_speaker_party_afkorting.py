"""widen speakers.party_afkorting

Stance extraction doesn't always yield a short abbreviation for `party` — it can
surface the full party name (e.g. "Forum voor Democratie", 22 chars) when the
source transcript's speaker isn't cleanly tagged with a fraction, which exceeded
the original String(20) limit and crashed the insert.

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-08-15
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "p9q0r1s2t3u4"
down_revision: Union[str, None] = "o8p9q0r1s2t3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("speakers", "party_afkorting", type_=sa.String(200))


def downgrade() -> None:
    op.alter_column("speakers", "party_afkorting", type_=sa.String(20))
