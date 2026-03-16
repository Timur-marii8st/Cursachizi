"""Add CASCADE deletes and credits non-negative constraint.

Revision ID: 6d4e5ae23b83
Revises: 0004_add_payments_table
Create Date: 2026-03-13 00:00:00.000000
"""

from alembic import op

revision = "6d4e5ae23b83"
down_revision = "0004_add_payments_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop existing FK constraints and re-create with CASCADE

    # Jobs table
    op.drop_constraint("jobs_user_id_fkey", "jobs", type_="foreignkey")
    op.create_foreign_key(
        "jobs_user_id_fkey",
        "jobs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Payments table
    op.drop_constraint("payments_user_id_fkey", "payments", type_="foreignkey")
    op.create_foreign_key(
        "payments_user_id_fkey",
        "payments",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add CHECK constraint to prevent negative credits
    op.create_check_constraint(
        "ck_users_credits_non_negative",
        "users",
        "credits_remaining >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_credits_non_negative", "users", type_="check")

    op.drop_constraint("payments_user_id_fkey", "payments", type_="foreignkey")
    op.create_foreign_key(
        "payments_user_id_fkey",
        "payments",
        "users",
        ["user_id"],
        ["id"],
    )

    op.drop_constraint("jobs_user_id_fkey", "jobs", type_="foreignkey")
    op.create_foreign_key(
        "jobs_user_id_fkey",
        "jobs",
        "users",
        ["user_id"],
        ["id"],
    )
