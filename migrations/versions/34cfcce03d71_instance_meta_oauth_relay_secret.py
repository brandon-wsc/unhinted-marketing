"""instance meta oauth relay secret

Revision ID: 34cfcce03d71
Revises: 80273a8317bb
Create Date: 2026-09-20 23:17:25.744347

ADR 0034 — per-install shared secret the vendor relay issues at registration:
authenticates one-time ticket redemption and relayed platform events
(deauthorize / data-deletion). Fernet-encrypted at rest like meta_app_secret;
last4 shown in the portal for confirmation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "34cfcce03d71"
down_revision: Union[str, None] = "80273a8317bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "instance_settings",
        sa.Column("meta_oauth_relay_secret_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "instance_settings",
        sa.Column("meta_oauth_relay_secret_last4", sa.String(length=4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instance_settings", "meta_oauth_relay_secret_last4")
    op.drop_column("instance_settings", "meta_oauth_relay_secret_encrypted")
