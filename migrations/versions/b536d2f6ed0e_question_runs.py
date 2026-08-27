"""question_runs + question_node_steps (ADR 0018 worker graph trace)

Tables: question_runs, question_node_steps

Revision ID: b536d2f6ed0e
Revises: 65936d4c8be7
Create Date: 2026-08-24 23:53:08.159416

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b536d2f6ed0e'
down_revision: Union[str, None] = '65936d4c8be7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "question_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column(
            "quality_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["entities.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_question_runs_company_id", "question_runs", ["company_id"])
    op.create_index("ix_question_runs_status", "question_runs", ["status"])
    op.create_index("ix_question_runs_started_at", "question_runs", ["started_at"])
    # ADR 0018 stampede guard: one active run per company, enforced by the DB
    # (multi-worker safe — no in-memory futures).
    op.create_index(
        "uq_question_runs_active_company",
        "question_runs",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "question_node_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=60), nullable=False),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["question_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_question_node_steps_run_id", "question_node_steps", ["run_id"])
    op.create_index("ix_question_node_steps_node", "question_node_steps", ["node"])
    op.create_index(
        "ix_question_node_steps_run_id_seq",
        "question_node_steps",
        ["run_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("uq_question_runs_active_company", table_name="question_runs")
    op.drop_index("ix_question_node_steps_run_id_seq", table_name="question_node_steps")
    op.drop_index("ix_question_node_steps_node", table_name="question_node_steps")
    op.drop_index("ix_question_node_steps_run_id", table_name="question_node_steps")
    op.drop_table("question_node_steps")
    op.drop_index("ix_question_runs_started_at", table_name="question_runs")
    op.drop_index("ix_question_runs_status", table_name="question_runs")
    op.drop_index("ix_question_runs_company_id", table_name="question_runs")
    op.drop_table("question_runs")
