"""invite_monthly_token_limit

org_invites.monthly_token_limit (per-invite spend cap preset, ADR 0042)

Revision ID: 25798eaf1549
Revises: 985b19ea73c9
Create Date: 2026-10-10 19:34:53.616093

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "25798eaf1549"
down_revision: Union[str, None] = "985b19ea73c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "org_invites",
        sa.Column("monthly_token_limit", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("org_invites", "monthly_token_limit")
