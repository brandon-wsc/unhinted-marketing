"""clear facebook social tokens

Tables: social_accounts (DELETE all rows — Facebook Login tokens cannot
publish on graph.instagram.com after the Instagram Login cutover)

Revision ID: a7c3e91f4b20
Revises: 6533adae4ac0
Create Date: 2026-09-06 13:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a7c3e91f4b20"
down_revision: Union[str, None] = "6533adae4ac0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM social_accounts")


def downgrade() -> None:
    # Facebook-era tokens cannot be restored.
    pass
