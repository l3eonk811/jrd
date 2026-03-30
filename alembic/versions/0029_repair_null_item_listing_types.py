"""Repair NULL listing_type for item-domain rows (deterministic; no guessing prices).

Revision ID: 0029
Revises: 0028
Create Date: 2026-03-28
"""

from alembic import op


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Portable SQL (PostgreSQL + SQLite): subqueries instead of UPDATE FROM.
    op.execute(
        """
        UPDATE items
        SET listing_type = 'adoption'
        WHERE listing_domain = 'item'
          AND (listing_type IS NULL OR listing_type = '')
          AND id IN (SELECT item_id FROM adoption_details)
        """
    )
    op.execute(
        """
        UPDATE items
        SET listing_type = 'sale'
        WHERE listing_domain = 'item'
          AND (listing_type IS NULL OR listing_type = '')
          AND price IS NOT NULL
          AND price > 0
        """
    )
    op.execute(
        """
        UPDATE items
        SET listing_type = 'donation'
        WHERE listing_domain = 'item'
          AND (listing_type IS NULL OR listing_type = '')
        """
    )


def downgrade() -> None:
    pass
