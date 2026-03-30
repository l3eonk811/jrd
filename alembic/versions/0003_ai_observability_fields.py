"""add ai observability fields to item_ai_analyses

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-06

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "item_ai_analyses",
        sa.Column("category_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "item_ai_analyses",
        sa.Column("used_fallback", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("item_ai_analyses", "used_fallback")
    op.drop_column("item_ai_analyses", "category_confidence")
