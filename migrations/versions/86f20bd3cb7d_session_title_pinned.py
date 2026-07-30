"""session title + pinned

Revision ID: 86f20bd3cb7d
Revises: 526ca8643303
Create Date: 2026-07-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "86f20bd3cb7d"
down_revision: Union[str, None] = "526ca8643303"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_sessions_pinned", "sessions", ["pinned"])


def downgrade() -> None:
    op.drop_index("ix_sessions_pinned", table_name="sessions")
    op.drop_column("sessions", "pinned")
    op.drop_column("sessions", "title")
