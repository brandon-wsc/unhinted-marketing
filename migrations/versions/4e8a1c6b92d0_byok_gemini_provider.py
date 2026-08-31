"""byok providers type check includes gemini

Revision ID: 4e8a1c6b92d0
Revises: 02862291031f
Create Date: 2026-08-31 02:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "4e8a1c6b92d0"
down_revision: Union[str, Sequence[str], None] = "02862291031f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_byok_providers_type", "byok_providers", type_="check")
    op.create_check_constraint(
        "ck_byok_providers_type",
        "byok_providers",
        "provider_type IN ('openai', 'anthropic', 'openai_compatible', 'gemini')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_byok_providers_type", "byok_providers", type_="check")
    op.create_check_constraint(
        "ck_byok_providers_type",
        "byok_providers",
        "provider_type IN ('openai', 'anthropic', 'openai_compatible')",
    )
