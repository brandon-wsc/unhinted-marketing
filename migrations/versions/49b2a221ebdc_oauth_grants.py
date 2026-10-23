"""oauth_grants

ADR 0051 — ``oauth_grants`` (user consent per external client x company x
scopes; access tokens carry only the grant id so revocation is live) plus
``sessions.origin`` (``{"kind": "mcp", grant_id, client_id, client_name,
auto_picks?}``; NULL for UI-started sessions).

Revision ID: 49b2a221ebdc
Revises: c3ea63ad10f8
Create Date: 2026-10-23 22:17:49.593643

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "49b2a221ebdc"
down_revision: Union[str, None] = "c3ea63ad10f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", sa.String(length=500), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_grants_user_id", "oauth_grants", ["user_id"])
    op.create_index("ix_oauth_grants_company_id", "oauth_grants", ["company_id"])
    op.add_column(
        "sessions",
        sa.Column("origin", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "origin")
    op.drop_index("ix_oauth_grants_company_id", table_name="oauth_grants")
    op.drop_index("ix_oauth_grants_user_id", table_name="oauth_grants")
    op.drop_table("oauth_grants")
