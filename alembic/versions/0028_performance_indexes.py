"""Hot-path indexes for discovery, messaging, and favorites (PostgreSQL).

Revision ID: 0028
Revises: 0027
Create Date: 2026-03-28

Partial index on items supports bbox + public discovery filters.
Conversation indexes support inbox ordering by participant + updated_at.
Messages composite supports thread fetches ordered by time.
"""

from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Public listings with coordinates — search_nearby / search_by_bounds hot path
    op.create_index(
        "ix_items_discover_lat_lon_partial",
        "items",
        ["latitude", "longitude"],
        postgresql_where=sa.text(
            "is_public IS true AND status = 'available' "
            "AND latitude IS NOT NULL AND longitude IS NOT NULL"
        ),
    )

    op.create_index(
        "ix_conversations_owner_updated",
        "conversations",
        ["owner_user_id", "updated_at"],
    )
    op.create_index(
        "ix_conversations_interested_updated",
        "conversations",
        ["interested_user_id", "updated_at"],
    )

    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
    )

    op.create_index(
        "ix_favorites_user_created",
        "favorites",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_index("ix_favorites_user_created", table_name="favorites")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_conversations_interested_updated", table_name="conversations")
    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.drop_index("ix_items_discover_lat_lon_partial", table_name="items")
