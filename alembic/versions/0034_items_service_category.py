"""Denormalized service_category on items for structured service taxonomy.

Revision ID: 0034
Revises: 0033
Create Date: 2026-03-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED = (
    "teacher",
    "delivery_driver",
    "electrician",
    "ac_technician",
    "plumber",
    "government_services",
    "babysitter",
    "carpenter",
    "construction",
    "security_guard",
    "events",
    "photographer",
    "barista",
    "other",
)


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("service_category", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_items_service_category", "items", ["service_category"], unique=False)

    in_list = ", ".join(f"'{x}'" for x in _ALLOWED)
    # PostgreSQL: backfill from service_details; legacy free text → other
    op.execute(
        f"""
        UPDATE items AS i
        SET service_category = CASE
            WHEN sd.service_category IN ({in_list}) THEN sd.service_category
            ELSE 'other'
        END
        FROM service_details AS sd
        WHERE sd.item_id = i.id AND i.listing_domain = 'service'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_items_service_category", table_name="items")
    op.drop_column("items", "service_category")
