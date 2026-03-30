"""add item status column

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-06

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add status column with default 'available' for backward compatibility
    op.add_column(
        "items",
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'available'")),
    )


def downgrade() -> None:
    op.drop_column("items", "status")
