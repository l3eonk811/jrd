"""conversations and messages for listing-contextual messaging

Revision ID: 0015
Revises: 0014
Create Date: 2026-03-18

Model:
- Conversation: one per (listing, interested_user) pair
- Message: N messages per conversation
- linked to a listing (item) + owner + interested party
- requests can optionally reference a conversation
"""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("interested_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        # optional link to a structured request that spawned this conversation
        sa.Column("item_request_id", sa.Integer,
                  sa.ForeignKey("item_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("item_id", "interested_user_id",
                            name="uq_conversation_item_user"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.Integer,
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("sender_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
