"""Add explicit text embedding reindex flags on items.

Revision ID: 0033
Revises: 0032
Create Date: 2026-03-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column(
            "text_embedding_needs_reindex",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "items",
        sa.Column("text_embedding_reindex_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Rows that already look indexed: clear explicit pending.
    op.execute(
        """
        UPDATE items SET text_embedding_needs_reindex = false
        WHERE text_embedding IS NOT NULL AND text_embedding_source_hash IS NOT NULL
        """
    )
    # Rows missing payload: need work.
    op.execute(
        """
        UPDATE items SET text_embedding_needs_reindex = true
        WHERE text_embedding IS NULL OR text_embedding_source_hash IS NULL
        """
    )
    op.create_index(
        "ix_items_text_embedding_needs_reindex",
        "items",
        ["text_embedding_needs_reindex"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_items_text_embedding_needs_reindex", table_name="items")
    op.drop_column("items", "text_embedding_reindex_requested_at")
    op.drop_column("items", "text_embedding_needs_reindex")
