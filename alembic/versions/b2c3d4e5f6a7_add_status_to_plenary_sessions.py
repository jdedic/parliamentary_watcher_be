"""add status to plenary_sessions

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE sessionstatus AS ENUM ('DOWNLOADED', 'FAILED')")
    op.add_column(
        "plenary_sessions",
        sa.Column(
            "status",
            sa.Enum("DOWNLOADED", "FAILED", name="sessionstatus"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("plenary_sessions", "status")
    op.execute("DROP TYPE sessionstatus")
