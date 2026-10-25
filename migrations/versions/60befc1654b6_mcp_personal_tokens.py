"""mcp_personal_tokens

ADR 0056 — static personal access tokens for headless MCP clients. The row
only resolves token -> grant; identity, scopes, and revocation all live on
``oauth_grants``.

Revision ID: 60befc1654b6
Revises: c1ec67133950
Create Date: 2026-10-25 23:34:25.839979

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '60befc1654b6'
down_revision: Union[str, None] = 'c1ec67133950'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_personal_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "grant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("oauth_grants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_personal_tokens")
