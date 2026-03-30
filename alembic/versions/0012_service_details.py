"""service_details table for service-specific listing fields

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-18

Creates service_details table linked 1-to-1 with items where listing_domain='service'.
Service-specific fields are cleanly isolated here instead of polluting items.
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_details",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"),
                  nullable=False, unique=True, index=True),
        sa.Column("service_category", sa.String(100), nullable=False),
        sa.Column("pricing_model", sa.String(30), nullable=False, server_default="negotiable"),
        # hourly | fixed | negotiable
        sa.Column("service_mode", sa.String(30), nullable=True),
        # at_client_location | at_provider_location | remote
        sa.Column("service_area", sa.String(200), nullable=True),
        sa.Column("availability_notes", sa.Text, nullable=True),
        sa.Column("experience_years", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("service_details")
