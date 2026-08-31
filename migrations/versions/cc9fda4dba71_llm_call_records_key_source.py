"""llm_call_records key_source + key_last4 (ADR 0020)

Revision ID: cc9fda4dba71
Revises: c33c4547fd8d
Create Date: 2026-08-30 15:48:50.554821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cc9fda4dba71"
down_revision: Union[str, Sequence[str], None] = "c33c4547fd8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_call_records",
        sa.Column("key_source", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "llm_call_records",
        sa.Column("key_last4", sa.String(length=4), nullable=True),
    )
    op.create_check_constraint(
        "ck_llm_call_records_key_source",
        "llm_call_records",
        "key_source IS NULL OR key_source IN ('env', 'org')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_call_records_key_source", "llm_call_records", type_="check")
    op.drop_column("llm_call_records", "key_last4")
    op.drop_column("llm_call_records", "key_source")
