"""add item_ai_analyses table

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-06

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_ai_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "image_id",
            sa.Integer(),
            sa.ForeignKey("item_images.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("suggested_title", sa.String(255), nullable=False),
        sa.Column("suggested_category", sa.String(100), nullable=False),
        sa.Column("suggested_condition", sa.String(50), nullable=False),
        sa.Column("suggested_tags", JSON, nullable=False, server_default="[]"),
        sa.Column("suggested_description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("ai_service", sa.String(50), nullable=False, server_default="mock"),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("image_size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_item_ai_analyses_item_id", "item_ai_analyses", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_item_ai_analyses_item_id", "item_ai_analyses")
    op.drop_table("item_ai_analyses")
