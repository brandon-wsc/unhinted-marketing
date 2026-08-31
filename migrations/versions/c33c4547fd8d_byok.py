"""byok_providers + byok_models + byok_routing (ADR 0020)

Tables: byok_providers, byok_models, byok_routing

Revision ID: c33c4547fd8d
Revises: b536d2f6ed0e
Create Date: 2026-08-30 15:05:00.521899

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c33c4547fd8d"
down_revision: Union[str, None] = "b536d2f6ed0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "byok_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("key_last4", sa.String(length=4), nullable=False),
        sa.Column("api_base", sa.String(length=500), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_kind", sa.String(length=40), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_byok_providers_id_company"),
    )
    op.create_index(
        op.f("ix_byok_providers_company_id"),
        "byok_providers",
        ["company_id"],
        unique=False,
    )

    op.create_table(
        "byok_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("capability", sa.String(length=16), nullable=False),
        sa.Column("capability_source", sa.String(length=32), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_kind", sa.String(length=40), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["provider_id", "company_id"],
            ["byok_providers.id", "byok_providers.company_id"],
            ondelete="CASCADE",
            name="fk_byok_models_provider_company",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_byok_models_id_company"),
        sa.UniqueConstraint("provider_id", "model_id", name="uq_byok_models_provider_model"),
    )
    op.create_index(
        op.f("ix_byok_models_company_id"),
        "byok_models",
        ["company_id"],
        unique=False,
    )

    op.create_table(
        "byok_routing",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cheap_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("medium_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("strong_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("image_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="CASCADE"),
        # PG 15+: SET NULL only the model column so company_id (PK) stays.
        sa.ForeignKeyConstraint(
            ["cheap_model_id", "company_id"],
            ["byok_models.id", "byok_models.company_id"],
            ondelete="SET NULL (cheap_model_id)",
            name="fk_byok_routing_cheap",
        ),
        sa.ForeignKeyConstraint(
            ["medium_model_id", "company_id"],
            ["byok_models.id", "byok_models.company_id"],
            ondelete="SET NULL (medium_model_id)",
            name="fk_byok_routing_medium",
        ),
        sa.ForeignKeyConstraint(
            ["strong_model_id", "company_id"],
            ["byok_models.id", "byok_models.company_id"],
            ondelete="SET NULL (strong_model_id)",
            name="fk_byok_routing_strong",
        ),
        sa.ForeignKeyConstraint(
            ["image_model_id", "company_id"],
            ["byok_models.id", "byok_models.company_id"],
            ondelete="SET NULL (image_model_id)",
            name="fk_byok_routing_image",
        ),
        sa.PrimaryKeyConstraint("company_id"),
    )


def downgrade() -> None:
    op.drop_table("byok_routing")
    op.drop_index(op.f("ix_byok_models_company_id"), table_name="byok_models")
    op.drop_table("byok_models")
    op.drop_index(op.f("ix_byok_providers_company_id"), table_name="byok_providers")
    op.drop_table("byok_providers")
