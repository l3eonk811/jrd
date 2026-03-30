"""app_settings key/value store for feature flags

Revision ID: 0025
Revises: 0024
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_app_settings_key", "app_settings", ["key"], unique=True)

    op.execute(
        sa.text(
            """
            INSERT INTO app_settings (key, value, description) VALUES
            ('max_images_per_listing', '20', 'Maximum number of images per listing'),
            ('enable_provider_ratings', 'true', 'When false, provider rating UI/API may be disabled by clients'),
            ('enable_ai_tags', 'true', 'Enable AI-assisted tagging where implemented'),
            ('default_show_phone_in_listing', 'false', 'Default visibility for phone on new listings'),
            ('report_auto_hide_threshold', '5', 'Reports count threshold for future auto-moderation')
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_app_settings_key", table_name="app_settings")
    op.drop_table("app_settings")
