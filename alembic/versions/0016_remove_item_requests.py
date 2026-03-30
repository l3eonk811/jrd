"""Remove item_requests table and decouple conversations

Revision ID: 0016
Revises: 0015
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop item_request_id FK and column from conversations
    with op.batch_alter_table("conversations") as batch_op:
        try:
            batch_op.drop_constraint("conversations_item_request_id_fkey", type_="foreignkey")
        except Exception:
            pass  # constraint may have a different name
        try:
            batch_op.drop_column("item_request_id")
        except Exception:
            pass  # column may already be absent

    # Drop item_requests table
    op.drop_table("item_requests")


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
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(
            sa.Column("item_request_id", sa.Integer,
                      sa.ForeignKey("item_requests.id", ondelete="SET NULL"), nullable=True)
        )
