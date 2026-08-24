"""session fork lineage (ADR 0017)

Adds fork lineage columns to ``sessions``:
``forked_from_session_id`` / ``forked_from_message_id`` / ``forked_from_title``.

Revision ID: 65936d4c8be7
Revises: c7e1a9b3d5f0
Create Date: 2026-08-24 01:34:11.531916

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65936d4c8be7'
down_revision: Union[str, None] = 'c7e1a9b3d5f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("forked_from_session_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("forked_from_message_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("forked_from_title", sa.String(length=200), nullable=True),
    )
    op.create_foreign_key(
        "fk_sessions_forked_from_session_id",
        "sessions",
        "sessions",
        ["forked_from_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sessions_forked_from_session_id", "sessions", ["forked_from_session_id"]
    )
    op.create_index(
        "ix_sessions_forked_from_message_id", "sessions", ["forked_from_message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_forked_from_message_id", table_name="sessions")
    op.drop_index("ix_sessions_forked_from_session_id", table_name="sessions")
    op.drop_constraint("fk_sessions_forked_from_session_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "forked_from_title")
    op.drop_column("sessions", "forked_from_message_id")
    op.drop_column("sessions", "forked_from_session_id")
