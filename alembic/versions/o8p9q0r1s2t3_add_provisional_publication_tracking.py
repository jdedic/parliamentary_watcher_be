"""add is_final/current_verslag_id to plenary_sessions, kind to plenary_session_documents

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-08-15
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "o8p9q0r1s2t3"
down_revision: Union[str, None] = "n7o8p9q0r1s2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plenary_sessions",
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "plenary_sessions",
        sa.Column("current_verslag_id", sa.String(), nullable=True),
    )
    op.add_column(
        "plenary_session_documents",
        sa.Column("kind", sa.String(), nullable=True),
    )

    # Backfill: every session/document that predates this migration was only ever
    # ingested via the old Eindpublicatie-only sync path, so it's safe to assume
    # every existing document is a final, corrected transcript. Without this, the
    # next sync would treat all of them as "pending" and pointlessly reprocess
    # every already-complete session.
    op.execute("UPDATE plenary_session_documents SET kind = 'Eindpublicatie' WHERE kind IS NULL")
    op.execute(
        """
        UPDATE plenary_sessions ps
        SET is_final = true,
            current_verslag_id = psd.document_id
        FROM plenary_session_documents psd
        WHERE psd.session_id = ps.id AND ps.current_verslag_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("plenary_session_documents", "kind")
    op.drop_column("plenary_sessions", "current_verslag_id")
    op.drop_column("plenary_sessions", "is_final")
