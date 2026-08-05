"""preview_images + preview_drafts.media_ids

Revision ID: 7d7a1918bde7
Revises: c8e4f1a2b3d0
Create Date: 2026-08-05

ADR 0008 — append-only preview_images; drafts reference ordered media_ids.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7d7a1918bde7"
down_revision: Union[str, None] = "c8e4f1a2b3d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "preview_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role", sa.String(length=40), nullable=False, server_default="primary"),
        sa.Column("format", sa.String(length=40), nullable=False, server_default="single"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="ready"),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "plan",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_preview_images_session_id", "preview_images", ["session_id"])

    op.add_column(
        "preview_drafts",
        sa.Column(
            "media_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
    )

    # Backfill one image row per draft that already had image_url.
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
              r RECORD;
              new_id uuid;
            BEGIN
              FOR r IN
                SELECT id, session_id, image_url, image_plan, created_at
                FROM preview_drafts
                WHERE image_url IS NOT NULL
              LOOP
                new_id := gen_random_uuid();
                INSERT INTO preview_images (
                  id, session_id, seq, role, format, status, url, plan, created_at
                ) VALUES (
                  new_id,
                  r.session_id,
                  0,
                  'primary',
                  COALESCE(r.image_plan->>'format', 'single'),
                  'ready',
                  r.image_url,
                  COALESCE(r.image_plan, '{}'::jsonb),
                  r.created_at
                );
                UPDATE preview_drafts
                SET media_ids = ARRAY[new_id]
                WHERE id = r.id;
              END LOOP;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.drop_column("preview_drafts", "media_ids")
    op.drop_index("ix_preview_images_session_id", table_name="preview_images")
    op.drop_table("preview_images")
