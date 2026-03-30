"""reports table (replace listing_reports), admin_audit_logs.details

Revision ID: 0024
Revises: 0023
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_audit_logs", sa.Column("details", sa.Text(), nullable=True))

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "reporter_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_reports_reporter_user_id", "reports", ["reporter_user_id"])
    op.create_index("ix_reports_target_type_target_id", "reports", ["target_type", "target_id"])
    op.create_index("ix_reports_status", "reports", ["status"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                INSERT INTO reports (id, reporter_user_id, target_type, target_id, reason, note, status, created_at)
                SELECT id, reporter_user_id, 'listing', item_id, reason, details, 'pending', created_at
                FROM listing_reports
                """
            )
        )
        op.execute(
            sa.text(
                "SELECT setval(pg_get_serial_sequence('reports', 'id'), "
                "COALESCE((SELECT MAX(id) FROM reports), 1))"
            )
        )
    else:
        op.execute(
            sa.text(
                """
                INSERT INTO reports (id, reporter_user_id, target_type, target_id, reason, note, status, created_at)
                SELECT id, reporter_user_id, 'listing', item_id, reason, details, 'pending', created_at
                FROM listing_reports
                """
            )
        )
        op.execute(
            sa.text(
                "INSERT OR REPLACE INTO sqlite_sequence(name, seq) "
                "SELECT 'reports', IFNULL(MAX(id), 0) FROM reports"
            )
        )

    op.drop_table("listing_reports")


def downgrade() -> None:
    op.create_table(
        "listing_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "reporter_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    bind = op.get_bind()
    op.execute(
        sa.text(
            """
            INSERT INTO listing_reports (id, item_id, reporter_user_id, reason, details, created_at)
            SELECT id, target_id, reporter_user_id, reason, note, created_at
            FROM reports
            WHERE target_type = 'listing'
            """
        )
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "SELECT setval(pg_get_serial_sequence('listing_reports', 'id'), "
                "COALESCE((SELECT MAX(id) FROM listing_reports), 1))"
            )
        )
    else:
        op.execute(
            sa.text(
                "INSERT OR REPLACE INTO sqlite_sequence(name, seq) "
                "SELECT 'listing_reports', IFNULL(MAX(id), 0) FROM listing_reports"
            )
        )

    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_target_type_target_id", table_name="reports")
    op.drop_index("ix_reports_reporter_user_id", table_name="reports")
    op.drop_table("reports")

    op.drop_column("admin_audit_logs", "details")
