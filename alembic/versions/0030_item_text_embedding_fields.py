"""Add text embedding columns to items (semantic search Phase S1; separate from image_embedding).

Revision ID: 0030
Revises: 0029
Create Date: 2026-03-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("text_embedding", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "items",
        sa.Column(
            "text_embedding_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "items",
        sa.Column("semantic_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("items", "semantic_text")
    op.drop_column("items", "text_embedding_updated_at")
    op.drop_column("items", "text_embedding")
