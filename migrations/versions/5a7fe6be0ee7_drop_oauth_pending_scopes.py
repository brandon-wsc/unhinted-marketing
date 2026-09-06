"""drop oauth pending scopes

Tables: social_accounts (drop unused oauth_pending_scopes leftover from
Facebook Login; Instagram Login never writes it)

Revision ID: 5a7fe6be0ee7
Revises: a7c3e91f4b20
Create Date: 2026-09-06 23:30:33.473107

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5a7fe6be0ee7"
down_revision: Union[str, None] = "a7c3e91f4b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("social_accounts", "oauth_pending_scopes")


def downgrade() -> None:
    op.add_column(
        "social_accounts",
        sa.Column("oauth_pending_scopes", sa.Text(), nullable=True),
    )
