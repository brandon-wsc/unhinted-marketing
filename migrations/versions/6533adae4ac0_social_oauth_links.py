"""social oauth links (ADR 0022 OAuth slice)

Tables: social_accounts (adds oauth_connect_state, oauth_pending_scopes)

Holds the in-progress Meta OAuth exchange (state + PKCE code verifier, encrypted)
and, after the token exchange, the FB user id and granted-scope gaps. The
access token itself still lives in access_token_encrypted (Fernet, BYOK key).

Revision ID: 6533adae4ac0
Revises: 4d9a7048ecc8
Create Date: 2026-09-03 23:46:06.718680

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6533adae4ac0"
down_revision: Union[str, None] = "4d9a7048ecc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "social_accounts",
        sa.Column("oauth_connect_state", sa.Text(), nullable=True),
    )
    op.add_column(
        "social_accounts",
        sa.Column("oauth_pending_scopes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("social_accounts", "oauth_pending_scopes")
    op.drop_column("social_accounts", "oauth_connect_state")
