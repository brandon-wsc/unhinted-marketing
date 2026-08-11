"""org_invites

Revision ID: e8f2a1b4c9d0
Revises: 12d5c92e3f74
Create Date: 2026-08-11

ADR 0010 — pending org invite tokens (hashed); partial unique on active invites.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8f2a1b4c9d0"
down_revision: Union[str, None] = "12d5c92e3f74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_org_invites_organization_id"),
        "org_invites",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_org_invites_token_hash"),
        "org_invites",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "uq_org_invites_pending_email",
        "org_invites",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_org_invites_pending_email", table_name="org_invites")
    op.drop_index(op.f("ix_org_invites_token_hash"), table_name="org_invites")
    op.drop_index(op.f("ix_org_invites_organization_id"), table_name="org_invites")
    op.drop_table("org_invites")
