"""add subcategory support to items and ai_analyses

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-06

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add subcategory to items table
    op.add_column(
        "items",
        sa.Column("subcategory", sa.String(length=100), nullable=True),
    )
    
    # Add subcategory fields to item_ai_analyses table
    op.add_column(
        "item_ai_analyses",
        sa.Column("suggested_subcategory", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "item_ai_analyses",
        sa.Column("subcategory_confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("item_ai_analyses", "subcategory_confidence")
    op.drop_column("item_ai_analyses", "suggested_subcategory")
    op.drop_column("items", "subcategory")
