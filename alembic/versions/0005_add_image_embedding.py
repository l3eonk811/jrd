"""add image_embedding column to items

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-06

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("image_embedding", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("items", "image_embedding")
