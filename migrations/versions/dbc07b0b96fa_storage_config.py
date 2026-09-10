"""storage_configs + storage_migrations + migration_done_keys (ADR 0025)

Tables: storage_configs, storage_migrations, migration_done_keys

Revision ID: dbc07b0b96fa
Revises: 5a7fe6be0ee7
Create Date: 2026-09-10 22:51:08.214670

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "dbc07b0b96fa"
down_revision: Union[str, None] = "5a7fe6be0ee7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "storage_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("backend", sa.String(length=16), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=True),
        sa.Column("endpoint_url", sa.String(length=500), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=False, server_default="us-east-1"),
        sa.Column("public_base_url", sa.String(length=500), nullable=True),
        sa.Column("access_key", sa.String(length=255), nullable=True),
        sa.Column("secret_key_encrypted", sa.Text(), nullable=True),
        sa.Column("secret_last4", sa.String(length=4), nullable=True),
        sa.Column(
            "seeded_from_env",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default="false", nullable=False),
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
            "backend IN ('local', 's3')",
            name="ck_storage_configs_backend",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_configs_company_id", "storage_configs", ["company_id"])
    op.create_index(
        "uq_storage_configs_one_active",
        "storage_configs",
        ["active"],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "storage_migrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="validating"),
        sa.Column("target_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "error_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "state IN ("
            "'validating', 'copying', 'verifying', 'ready_to_flip', "
            "'flipping', 'completed', 'cleaning', 'done', 'failed'"
            ")",
            name="ck_storage_migrations_state",
        ),
        sa.ForeignKeyConstraint(
            ["target_config_id"], ["storage_configs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_config_id"], ["storage_configs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "migration_done_keys",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "migrated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("migration_done_keys")
    op.drop_table("storage_migrations")
    op.drop_index("uq_storage_configs_one_active", table_name="storage_configs")
    op.drop_index("ix_storage_configs_company_id", table_name="storage_configs")
    op.drop_table("storage_configs")
