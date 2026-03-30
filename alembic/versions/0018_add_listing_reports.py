"""Add listing_reports table

Revision ID: 0018
Revises: 0017
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listing_reports",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("item_id", sa.Integer,
                  sa.ForeignKey("items.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("reporter_user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("listing_reports")
