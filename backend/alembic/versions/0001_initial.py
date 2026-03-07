"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("university", sa.String(length=200), nullable=False),
        sa.Column("credits_remaining", sa.Integer(), nullable=False),
        sa.Column("total_papers_generated", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("university", sa.String(length=200), nullable=False),
        sa.Column("discipline", sa.String(length=200), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("template_id", sa.String(length=50), nullable=True),
        sa.Column("additional_instructions", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("progress_pct", sa.Integer(), nullable=False),
        sa.Column("stage_message", sa.Text(), nullable=False),
        sa.Column("pipeline_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("research_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("outline_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fact_check_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("document_s3_key", sa.String(length=500), nullable=True),
        sa.Column("document_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("total_input_tokens", sa.Integer(), nullable=False),
        sa.Column("total_output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_user_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
