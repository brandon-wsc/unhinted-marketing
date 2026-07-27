"""raw_news_events, edges, recommended_questions

Revision ID: 5dae474953cd
Revises: 8791b607d5bc
Create Date: 2026-07-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5dae474953cd"
down_revision: Union[str, None] = "8791b607d5bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "raw_news_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("region", sa.String(length=10), nullable=False, server_default="HK"),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id"),
        sa.UniqueConstraint("url_hash"),
    )
    op.create_index("ix_raw_news_events_source", "raw_news_events", ["source"])
    op.create_index("ix_raw_news_events_ingested_at", "raw_news_events", ["ingested_at"])

    op.create_table(
        "edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("edge_type", sa.String(length=40), nullable=False),
        sa.Column("source_signal_id", sa.String(length=200), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["from_entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_edges_source_signal_id", "edges", ["source_signal_id"])
    op.create_index("ix_edges_edge_type", "edges", ["edge_type"])

    op.create_table(
        "recommended_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_signal_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recommended_questions_company_expires",
        "recommended_questions",
        ["company_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommended_questions_company_expires", table_name="recommended_questions")
    op.drop_table("recommended_questions")
    op.drop_index("ix_edges_edge_type", table_name="edges")
    op.drop_index("ix_edges_source_signal_id", table_name="edges")
    op.drop_table("edges")
    op.drop_index("ix_raw_news_events_ingested_at", table_name="raw_news_events")
    op.drop_index("ix_raw_news_events_source", table_name="raw_news_events")
    op.drop_table("raw_news_events")
