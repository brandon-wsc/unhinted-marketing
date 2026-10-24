"""oauth_flow

ADR 0051 — pending authorize requests (``oauth_auth_requests``), single-use
hashed authorization codes (``oauth_codes``), rotating grant refresh tokens
(``oauth_refresh_tokens``), and the ``uq_oauth_grant`` unique constraint so
re-consent upserts rather than duplicating a grant.

Revision ID: c1ec67133950
Revises: 49b2a221ebdc
Create Date: 2026-10-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c1ec67133950"
down_revision: Union[str, None] = "49b2a221ebdc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_auth_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", sa.String(length=500), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("redirect_uri", sa.String(length=500), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=500), nullable=False),
        sa.Column("code_challenge", sa.String(length=200), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "oauth_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", sa.String(length=500), nullable=False),
        sa.Column("redirect_uri", sa.String(length=500), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=False),
        sa.Column("code_challenge", sa.String(length=200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["grant_id"], ["oauth_grants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_oauth_refresh_tokens_grant_id", "oauth_refresh_tokens", ["grant_id"])
    op.create_index("ix_oauth_refresh_tokens_family_id", "oauth_refresh_tokens", ["family_id"])
    op.create_unique_constraint(
        "uq_oauth_grant", "oauth_grants", ["user_id", "client_id", "company_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_oauth_grant", "oauth_grants", type_="unique")
    op.drop_index("ix_oauth_refresh_tokens_family_id", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_tokens_grant_id", table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_auth_requests")
