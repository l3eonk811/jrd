"""adoption_details table for animal-specific listing fields

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-18

Creates adoption_details table — isolated from Item so non-adoption
listings are not polluted with nullable animal fields.
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adoption_details",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"),
                  nullable=False, unique=True, index=True),
        sa.Column("animal_type", sa.String(100), nullable=False),
        sa.Column("age", sa.String(50), nullable=True),
        sa.Column("gender", sa.String(20), nullable=True),
        sa.Column("health_status", sa.Text, nullable=True),
        sa.Column("vaccinated_status", sa.String(30), nullable=True),   # vaccinated | not_vaccinated | unknown
        sa.Column("neutered_status", sa.String(30), nullable=True),     # neutered | not_neutered | unknown
        sa.Column("adoption_reason", sa.Text, nullable=True),
        sa.Column("special_experience_required", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("adoption_details")
