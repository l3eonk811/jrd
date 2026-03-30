"""Add text_embedding_source_hash for stale detection (SHA-256 hex of embedded semantic_text).

Revision ID: 0031
Revises: 0030
Create Date: 2026-03-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("text_embedding_source_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("items", "text_embedding_source_hash")
