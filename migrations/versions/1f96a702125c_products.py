"""products catalog (org + user libraries)

Revision ID: 1f96a702125c
Revises: 7d7a1918bde7
Create Date: 2026-08-10

Knowledge COLLECT K3/K3b — dedicated products table with owner_scope.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1f96a702125c"
down_revision: Union[str, None] = "7d7a1918bde7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_scope", sa.String(length=10), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sku", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("search_document", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
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
            "owner_scope IN ('org', 'user')",
            name="ck_products_owner_scope",
        ),
        sa.CheckConstraint(
            "(owner_scope = 'org' AND user_id IS NULL) OR "
            "(owner_scope = 'user' AND user_id IS NOT NULL)",
            name="ck_products_scope_user",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_products_status",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_company_id", "products", ["company_id"])
    op.create_index("ix_products_company_status", "products", ["company_id", "status"])
    op.create_index(
        "uq_products_org_sku",
        "products",
        ["company_id", "sku"],
        unique=True,
        postgresql_where=sa.text("owner_scope = 'org'"),
    )
    op.create_index(
        "uq_products_user_sku",
        "products",
        ["company_id", "user_id", "sku"],
        unique=True,
        postgresql_where=sa.text("owner_scope = 'user'"),
    )


def downgrade() -> None:
    op.drop_index("uq_products_user_sku", table_name="products")
    op.drop_index("uq_products_org_sku", table_name="products")
    op.drop_index("ix_products_company_status", table_name="products")
    op.drop_index("ix_products_company_id", table_name="products")
    op.drop_table("products")
