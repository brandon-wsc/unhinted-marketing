"""byok enum and api_base check constraints

Revision ID: 02862291031f
Revises: cc9fda4dba71
Create Date: 2026-08-30 16:22:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "02862291031f"
down_revision: Union[str, Sequence[str], None] = "cc9fda4dba71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_byok_providers_type",
        "byok_providers",
        "provider_type IN ('openai', 'anthropic', 'openai_compatible')",
    )
    op.create_check_constraint(
        "ck_byok_providers_api_base",
        "byok_providers",
        "provider_type <> 'openai_compatible' OR "
        "(api_base IS NOT NULL AND btrim(api_base) <> '')",
    )
    op.create_check_constraint(
        "ck_byok_models_capability",
        "byok_models",
        "capability IN ('chat', 'image')",
    )
    op.create_check_constraint(
        "ck_byok_models_capability_source",
        "byok_models",
        "capability_source IN ('provider_metadata', 'inferred', 'manual')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_byok_models_capability_source", "byok_models", type_="check")
    op.drop_constraint("ck_byok_models_capability", "byok_models", type_="check")
    op.drop_constraint("ck_byok_providers_api_base", "byok_providers", type_="check")
    op.drop_constraint("ck_byok_providers_type", "byok_providers", type_="check")
