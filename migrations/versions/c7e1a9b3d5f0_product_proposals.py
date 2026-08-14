"""product_proposals

Revision ID: c7e1a9b3d5f0
Revises: e8f2a1b4c9d0
Create Date: 2026-08-14

ADR 0011 — pending Mine → org product proposals; partial unique on pending SKU.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e1a9b3d5f0"
down_revision: Union[str, None] = "e8f2a1b4c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("proposed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sku", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_proposals_company_id"),
        "product_proposals",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "uq_product_proposals_pending_sku",
        "product_proposals",
        ["company_id", "sku"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_product_proposals_pending_sku", table_name="product_proposals")
    op.drop_index(op.f("ix_product_proposals_company_id"), table_name="product_proposals")
    op.drop_table("product_proposals")
