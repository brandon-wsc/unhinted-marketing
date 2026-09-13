"""instance_settings

Revision ID: 2e08021a6e54
Revises: dbc07b0b96fa
Create Date: 2026-09-13

ADR 0026 — singleton row holding deployment-wide settings (web base URL,
email/SMTP delivery, setup marker). Existing deployments (any users present)
are marked setup-complete so they never see the first-run wizard.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2e08021a6e54"
down_revision: Union[str, None] = "dbc07b0b96fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instance_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("web_base_url", sa.String(length=500), nullable=True),
        sa.Column(
            "email_backend",
            sa.String(length=16),
            nullable=False,
            server_default="link",
        ),
        sa.Column("email_from", sa.String(length=320), nullable=True),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_user", sa.String(length=255), nullable=True),
        sa.Column("smtp_password_encrypted", sa.Text(), nullable=True),
        sa.Column("smtp_password_last4", sa.String(length=4), nullable=True),
        sa.Column("smtp_tls", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_instance_settings_singleton"),
        sa.CheckConstraint(
            "email_backend IN ('link', 'smtp', 'console')",
            name="ck_instance_settings_email_backend",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Seed the singleton; deployments that already have users are treated as
    # setup-complete and skip the wizard entirely.
    op.execute(
        sa.text(
            "INSERT INTO instance_settings (id, setup_completed_at) "
            "SELECT 1, CASE WHEN EXISTS (SELECT 1 FROM users) THEN now() ELSE NULL END"
        )
    )


def downgrade() -> None:
    op.drop_table("instance_settings")
