"""add work_type column to jobs

Revision ID: 0002_add_work_type
Revises: 0001_initial
Create Date: 2026-03-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_add_work_type"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("work_type", sa.String(20), server_default="coursework", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("jobs", "work_type")
