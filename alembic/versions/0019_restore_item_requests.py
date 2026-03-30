"""Restore item_requests table for marketplace request workflow

Revision ID: 0019
Revises: 0018
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_requests",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("requester_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("response_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_item_requests_status", "item_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_item_requests_status", table_name="item_requests")
    op.drop_table("item_requests")
