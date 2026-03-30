"""user is_admin and is_blocked for admin console

Revision ID: 0022
Revises: 0021
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("users", "is_admin", server_default=None)
    op.alter_column("users", "is_blocked", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "is_blocked")
    op.drop_column("users", "is_admin")
