"""meta oauth byo

Revision ID: 50d26ea1a130
Revises: 2e08021a6e54
Create Date: 2026-09-20 02:30:51.071598

ADR 0032 — on-prem Meta OAuth defaults to a BYO app held on the
instance_settings singleton (env seeds, portal wins); meta_oauth_mode
reserves the opt-in vendor relay.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "50d26ea1a130"
down_revision: Union[str, None] = "2e08021a6e54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "instance_settings",
        sa.Column("meta_app_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "instance_settings",
        sa.Column("meta_app_secret_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "instance_settings",
        sa.Column("meta_app_secret_last4", sa.String(length=4), nullable=True),
    )
    op.add_column(
        "instance_settings",
        sa.Column(
            "meta_oauth_mode",
            sa.String(length=16),
            nullable=False,
            server_default="byo",
        ),
    )
    op.create_check_constraint(
        "ck_instance_settings_meta_oauth_mode",
        "instance_settings",
        "meta_oauth_mode IN ('byo', 'relay')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_instance_settings_meta_oauth_mode", "instance_settings", type_="check"
    )
    op.drop_column("instance_settings", "meta_oauth_mode")
    op.drop_column("instance_settings", "meta_app_secret_last4")
    op.drop_column("instance_settings", "meta_app_secret_encrypted")
    op.drop_column("instance_settings", "meta_app_id")
