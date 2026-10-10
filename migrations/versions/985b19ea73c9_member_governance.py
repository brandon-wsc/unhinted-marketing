"""member_governance

organization_members.monthly_token_limit (per-member platform-key cap, ADR 0041)
+ ix_tool_receipts_status (publish-approval queue listing)

Revision ID: 985b19ea73c9
Revises: bc2dadfe3ebd
Create Date: 2026-10-10 00:28:33.063864

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "985b19ea73c9"
down_revision: Union[str, None] = "bc2dadfe3ebd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organization_members",
        sa.Column("monthly_token_limit", sa.Integer(), nullable=True),
    )
    op.create_index("ix_tool_receipts_status", "tool_receipts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tool_receipts_status", table_name="tool_receipts")
    op.drop_column("organization_members", "monthly_token_limit")
