"""add item_requests table

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-06

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("response_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_item_requests_id", "item_requests", ["id"])
    op.create_index("ix_item_requests_item_id", "item_requests", ["item_id"])
    op.create_index("ix_item_requests_requester_id", "item_requests", ["requester_id"])
    op.create_index("ix_item_requests_status", "item_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_item_requests_status", table_name="item_requests")
    op.drop_index("ix_item_requests_requester_id", table_name="item_requests")
    op.drop_index("ix_item_requests_item_id", table_name="item_requests")
    op.drop_index("ix_item_requests_id", table_name="item_requests")
    op.drop_table("item_requests")
