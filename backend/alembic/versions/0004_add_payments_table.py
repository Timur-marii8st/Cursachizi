"""add payments table

Revision ID: 0004_add_payments_table
Revises: 0003_add_reference_s3_key
Create Date: 2026-03-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_add_payments_table"
down_revision = "0003_add_reference_s3_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("package_id", sa.String(20), nullable=False),
        sa.Column("credits", sa.Integer, nullable=False),
        sa.Column("amount_rub", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("robokassa_inv_id", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("payments")
