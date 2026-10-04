"""products embedding hnsw index

Revision ID: bc2dadfe3ebd
Revises: eb81088ac028
Create Date: 2026-10-05

COLLECT K4 — ANN index so product retrieve can run cosine top-K in Postgres
(<=> / vector_cosine_ops) instead of scanning rows into Python.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "bc2dadfe3ebd"
down_revision: Union[str, None] = "eb81088ac028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_products_embedding_hnsw",
        "products",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_products_embedding_hnsw", table_name="products")
