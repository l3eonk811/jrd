"""Add users.role for admin RBAC (simple string roles)

Revision ID: 0026
Revises: 0025
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

ALLOWED = ("super_admin", "moderator", "support", "viewer")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(32),
            nullable=False,
            server_default="viewer",
        ),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.execute(
        sa.text("UPDATE users SET role = 'super_admin' WHERE is_admin = true AND role = 'viewer'")
    )


def downgrade() -> None:
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "role")
