"""provider ratings (per provider user, not per listing)

Revision ID: 0021
Revises: 0020
Create Date: 2026-03-28

Adds provider_ratings: one row per (rater, provider), editable stars + optional comment.
"""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_ratings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rater_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider_user_id", "rater_user_id", name="uq_provider_ratings_provider_rater"),
    )
    op.create_index("ix_provider_ratings_provider_user_id", "provider_ratings", ["provider_user_id"])
    op.create_index("ix_provider_ratings_rater_user_id", "provider_ratings", ["rater_user_id"])


def downgrade() -> None:
    op.drop_index("ix_provider_ratings_rater_user_id", table_name="provider_ratings")
    op.drop_index("ix_provider_ratings_provider_user_id", table_name="provider_ratings")
    op.drop_table("provider_ratings")
