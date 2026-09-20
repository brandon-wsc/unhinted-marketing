"""instance meta oauth relay

Revision ID: 80273a8317bb
Revises: 50d26ea1a130
Create Date: 2026-09-20 14:54:48.864423

ADR 0032 §3 — opt-in vendor relay: meta_oauth_relay_url holds the relay base
(env OAUTH_RELAY_URL seeds, portal wins); meta_oauth_instance_id is the
REGISTRY slug the relay maps to this install's web_base_url.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "80273a8317bb"
down_revision: Union[str, None] = "50d26ea1a130"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "instance_settings",
        sa.Column("meta_oauth_relay_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "instance_settings",
        sa.Column("meta_oauth_instance_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instance_settings", "meta_oauth_instance_id")
    op.drop_column("instance_settings", "meta_oauth_relay_url")
