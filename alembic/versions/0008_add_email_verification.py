"""add email verification to users

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-07

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add email verification columns
    op.add_column("users", sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("verification_token", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("verification_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    
    # Add indexes
    op.create_index("ix_users_verification_token", "users", ["verification_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_verification_token", table_name="users")
    op.drop_column("users", "verification_token_expires_at")
    op.drop_column("users", "verification_token")
    op.drop_column("users", "is_email_verified")
