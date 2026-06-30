"""create initial tables

Revision ID: 0001
Revises:
Create Date: 2026-06-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column("lang", sa.String(5), nullable=False, server_default="uz"),
    )

    op.create_table(
        "parent_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("parent_name", sa.String(100), nullable=True),
        sa.Column("student_platform_id", sa.Integer(), nullable=False),
        sa.Column("student_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("parent_subscriptions")
    op.drop_table("user_settings")
