"""llm_call_records ttft_ms + cached_tokens

Revision ID: 115c56e66d3a
Revises: 34cfcce03d71
Create Date: 2026-09-25 15:22:49.723820

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '115c56e66d3a'
down_revision: Union[str, None] = '34cfcce03d71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_call_records",
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_call_records",
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_call_records", "cached_tokens")
    op.drop_column("llm_call_records", "ttft_ms")
