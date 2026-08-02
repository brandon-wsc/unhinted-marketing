"""llm_call_records + users.platform_level (ADR 0005)

Revision ID: b79dd0a3a6eb
Revises: 86f20bd3cb7d
Create Date: 2026-08-03 00:32:06.625321

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b79dd0a3a6eb'
down_revision: Union[str, None] = '86f20bd3cb7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ADR 0005 platform privilege ladder (MEMBER=3 default for existing rows).
    op.add_column(
        "users",
        sa.Column("platform_level", sa.Integer(), nullable=False, server_default="3"),
    )

    op.create_table(
        "llm_call_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("caller", sa.String(length=80), nullable=False),
        sa.Column("node", sa.String(length=60), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("user_prompt", sa.Text(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parse_ok", sa.Boolean(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_call_records_caller", "llm_call_records", ["caller"])
    op.create_index("ix_llm_call_records_node", "llm_call_records", ["node"])
    op.create_index("ix_llm_call_records_session_id", "llm_call_records", ["session_id"])
    op.create_index("ix_llm_call_records_status", "llm_call_records", ["status"])
    op.create_index("ix_llm_call_records_created_at", "llm_call_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_records_created_at", table_name="llm_call_records")
    op.drop_index("ix_llm_call_records_status", table_name="llm_call_records")
    op.drop_index("ix_llm_call_records_session_id", table_name="llm_call_records")
    op.drop_index("ix_llm_call_records_node", table_name="llm_call_records")
    op.drop_index("ix_llm_call_records_caller", table_name="llm_call_records")
    op.drop_table("llm_call_records")
    op.drop_column("users", "platform_level")
