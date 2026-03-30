"""user profile, contact, and privacy fields

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-18

Adds to users table:
- display_name   visible name shown on listings (defaults to username)
- bio            short optional bio
- city           city/region text (optional)
- phone_number   private by default; shown only when explicitly allowed
- allow_messages_default   profile-level messaging preference
- allow_phone_default      profile-level phone visibility preference
"""

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("bio", sa.Text, nullable=True))
    op.add_column("users", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("phone_number", sa.String(30), nullable=True))
    op.add_column("users", sa.Column("allow_messages_default", sa.Boolean,
                                     nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("allow_phone_default", sa.Boolean,
                                     nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "allow_phone_default")
    op.drop_column("users", "allow_messages_default")
    op.drop_column("users", "phone_number")
    op.drop_column("users", "city")
    op.drop_column("users", "bio")
    op.drop_column("users", "display_name")
