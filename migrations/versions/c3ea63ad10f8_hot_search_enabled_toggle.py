"""hot_search_enabled_toggle

ADR 0050 — ``instance_settings.scheduler_hot_search_enabled``: NULL = env
default (``SCHEDULER_HOT_SEARCH_ENABLED``, true). Gates the periodic hot tick
(hot_search + promote_signals enqueue); manual runs are unaffected.

Revision ID: c3ea63ad10f8
Revises: 39a74bf0c2ca
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3ea63ad10f8'
down_revision: Union[str, None] = '39a74bf0c2ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "instance_settings",
        sa.Column("scheduler_hot_search_enabled", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instance_settings", "scheduler_hot_search_enabled")
