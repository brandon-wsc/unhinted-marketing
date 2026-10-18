"""attachments

Revision ID: 67fad31a3691
Revises: 25798eaf1549
Create Date: 2026-10-18

ADR 0047 — session file attachments: `attachments` file rows with owner
scope + ingest status, `document_chunks` (dimensionless pgvector so a
second embedding space is possible later), and the `attachment_sessions`
join that shares an attachment across forked sessions by reference.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "67fad31a3691"
down_revision: Union[str, None] = "25798eaf1549"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_scope", sa.String(length=10), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "doc_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "owner_scope IN ('session', 'user', 'org')",
            name="ck_attachments_owner_scope",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready_lexical', 'ready', 'failed')",
            name="ck_attachments_status",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attachments_company_id", "attachments", ["company_id"])
    op.create_index("ix_attachments_session_id", "attachments", ["session_id"])

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attachment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attachment_id", "chunk_index", name="uq_document_chunks_attachment_index"
        ),
    )
    op.create_index("ix_document_chunks_attachment_id", "document_chunks", ["attachment_id"])
    # Dimensionless on purpose (ADR 0047 §9): a second embedding space can land
    # later without re-migration; retrieve always filters embedding_model.
    op.execute(sa.text("ALTER TABLE document_chunks ADD COLUMN embedding vector"))

    op.create_table(
        "attachment_sessions",
        sa.Column("attachment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attachment_id", "session_id"),
    )
    op.create_index("ix_attachment_sessions_session_id", "attachment_sessions", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_attachment_sessions_session_id", table_name="attachment_sessions")
    op.drop_table("attachment_sessions")
    op.drop_index("ix_document_chunks_attachment_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_attachments_session_id", table_name="attachments")
    op.drop_index("ix_attachments_company_id", table_name="attachments")
    op.drop_table("attachments")
