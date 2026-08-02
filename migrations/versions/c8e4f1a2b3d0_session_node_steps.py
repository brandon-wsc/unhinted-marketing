"""session_node_steps + llm_call_records.turn_id

Revision ID: c8e4f1a2b3d0
Revises: b79dd0a3a6eb
Create Date: 2026-08-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8e4f1a2b3d0"
down_revision: Union[str, Sequence[str], None] = "b79dd0a3a6eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_call_records",
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_llm_call_records_turn_id", "llm_call_records", ["turn_id"])

    op.create_table(
        "session_node_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=60), nullable=False),
        sa.Column("mode_in", sa.String(length=40), nullable=True),
        sa.Column("mode_out", sa.String(length=40), nullable=True),
        sa.Column("intent_out", sa.String(length=40), nullable=True),
        sa.Column(
            "source_signal_ids_in",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_signal_ids_out",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "output_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_session_node_steps_session_id", "session_node_steps", ["session_id"])
    op.create_index("ix_session_node_steps_turn_id", "session_node_steps", ["turn_id"])
    op.create_index("ix_session_node_steps_node", "session_node_steps", ["node"])
    op.create_index("ix_session_node_steps_created_at", "session_node_steps", ["created_at"])
    op.create_index(
        "ix_session_node_steps_turn_id_seq",
        "session_node_steps",
        ["turn_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_node_steps_turn_id_seq", table_name="session_node_steps")
    op.drop_index("ix_session_node_steps_created_at", table_name="session_node_steps")
    op.drop_index("ix_session_node_steps_node", table_name="session_node_steps")
    op.drop_index("ix_session_node_steps_turn_id", table_name="session_node_steps")
    op.drop_index("ix_session_node_steps_session_id", table_name="session_node_steps")
    op.drop_table("session_node_steps")
    op.drop_index("ix_llm_call_records_turn_id", table_name="llm_call_records")
    op.drop_column("llm_call_records", "turn_id")
