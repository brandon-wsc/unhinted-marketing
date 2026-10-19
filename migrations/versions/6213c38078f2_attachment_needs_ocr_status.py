"""attachment_needs_ocr_status

ADR 0048 §1 — ``attachments.status`` gains ``needs_ocr``: a no-text-layer
document parks for client OCR instead of failing permanently.

Revision ID: 6213c38078f2
Revises: 67fad31a3691
Create Date: 2026-10-19 15:50:55.031489

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6213c38078f2'
down_revision: Union[str, None] = '67fad31a3691'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_attachments_status", "attachments", type_="check")
    op.create_check_constraint(
        "ck_attachments_status",
        "attachments",
        "status IN ('pending', 'ready_lexical', 'ready', 'failed', 'needs_ocr')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_attachments_status", "attachments", type_="check")
    op.create_check_constraint(
        "ck_attachments_status",
        "attachments",
        "status IN ('pending', 'ready_lexical', 'ready', 'failed')",
    )
