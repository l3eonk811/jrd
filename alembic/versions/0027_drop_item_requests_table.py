"""Drop item_requests table (request workflow removed)

Revision ID: 0027
Revises: 0026
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS item_requests"))


def downgrade() -> None:
    op.create_table(
        "item_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requester_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("response_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_item_requests_status", "item_requests", ["status"])
