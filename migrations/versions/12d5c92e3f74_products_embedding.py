"""products embedding (pgvector)

Revision ID: 12d5c92e3f74
Revises: 1f96a702125c
Create Date: 2026-08-10

Knowledge COLLECT K4 — vector column on products for hybrid retrieve.
Dim 384 matches paraphrase-multilingual-MiniLM-L12-v2 (semantic gate family).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "12d5c92e3f74"
down_revision: Union[str, None] = "1f96a702125c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep in sync with internal.memory.embeddings.EMBEDDING_DIM
_EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(
        sa.text(f"ALTER TABLE products ADD COLUMN embedding vector({_EMBEDDING_DIM})")
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE products DROP COLUMN IF EXISTS embedding"))
