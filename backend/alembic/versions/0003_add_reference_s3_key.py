"""add reference_s3_key column to jobs

Revision ID: 0003_add_reference_s3_key
Revises: 0002_add_work_type
Create Date: 2026-03-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_add_reference_s3_key"
down_revision = "0002_add_work_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("reference_s3_key", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "reference_s3_key")
