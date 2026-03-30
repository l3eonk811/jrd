"""Message location shares + user blocks for messaging

Revision ID: 0020
Revises: 0019
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("message_kind", sa.String(20), nullable=False, server_default="text"),
    )
    op.add_column("messages", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("messages", sa.Column("longitude", sa.Float(), nullable=True))
    op.execute("UPDATE messages SET message_kind = 'text' WHERE message_kind IS NULL")
    op.alter_column("messages", "message_kind", server_default=None)

    op.create_table(
        "user_blocks",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("blocker_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("blocked_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocks_pair"),
    )


def downgrade() -> None:
    op.drop_table("user_blocks")
    op.drop_column("messages", "longitude")
    op.drop_column("messages", "latitude")
    op.drop_column("messages", "message_kind")
