"""ingest schedule instance settings

ADR 0050 — ``instance_settings`` gains the ingest schedule knobs:
``scheduler_hot_search_interval_minutes``, ``scheduler_questions_interval_hours``,
``news_promote_window_hours``, ``news_promote_trends_rank_max``.
All nullable — NULL means the env value is the effective default.

Revision ID: 39a74bf0c2ca
Revises: 6213c38078f2
Create Date: 2026-10-20 01:00:28.446822

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39a74bf0c2ca'
down_revision: Union[str, None] = '6213c38078f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    "scheduler_hot_search_interval_minutes",
    "scheduler_questions_interval_hours",
    "news_promote_window_hours",
    "news_promote_trends_rank_max",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("instance_settings", sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    for name in _COLUMNS:
        op.drop_column("instance_settings", name)
