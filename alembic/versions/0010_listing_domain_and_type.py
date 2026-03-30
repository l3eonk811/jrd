"""listing domain, type, price, and per-listing contact controls

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-18

Adds:
- items.listing_domain  ('item' | 'service', default 'item')
- items.listing_type    ('sale' | 'donation' | 'adoption', nullable — null for services)
- items.price           (Float, nullable)
- items.currency        (String, default 'SAR')
- items.show_phone_in_listing (Boolean, default False)
- items.allow_messages  (Boolean, default True)
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("listing_domain", sa.String(20), nullable=False, server_default="item"))
    op.add_column("items", sa.Column("listing_type", sa.String(20), nullable=True))
    op.add_column("items", sa.Column("price", sa.Float, nullable=True))
    op.add_column("items", sa.Column("currency", sa.String(10), nullable=False, server_default="SAR"))
    op.add_column("items", sa.Column("show_phone_in_listing", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("items", sa.Column("allow_messages", sa.Boolean, nullable=False, server_default=sa.true()))

    # Back-fill: existing items are 'item' domain, listing_type 'donation' (neutral default)
    op.execute("UPDATE items SET listing_type = 'donation' WHERE listing_domain = 'item' AND listing_type IS NULL")

    op.create_index("ix_items_listing_domain", "items", ["listing_domain"])
    op.create_index("ix_items_listing_type", "items", ["listing_type"])


def downgrade() -> None:
    op.drop_index("ix_items_listing_type", "items")
    op.drop_index("ix_items_listing_domain", "items")
    op.drop_column("items", "allow_messages")
    op.drop_column("items", "show_phone_in_listing")
    op.drop_column("items", "currency")
    op.drop_column("items", "price")
    op.drop_column("items", "listing_type")
    op.drop_column("items", "listing_domain")
