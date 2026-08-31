"""byok providers type check includes vertex_ai

Revision ID: b16fe8f23a68
Revises: 4e8a1c6b92d0
Create Date: 2026-08-31 02:41:12.956917

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b16fe8f23a68"
down_revision: Union[str, Sequence[str], None] = "4e8a1c6b92d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_byok_providers_type", "byok_providers", type_="check")
    op.create_check_constraint(
        "ck_byok_providers_type",
        "byok_providers",
        "provider_type IN ('openai', 'anthropic', 'openai_compatible', 'gemini', 'vertex_ai')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_byok_providers_type", "byok_providers", type_="check")
    op.create_check_constraint(
        "ck_byok_providers_type",
        "byok_providers",
        "provider_type IN ('openai', 'anthropic', 'openai_compatible', 'gemini')",
    )
