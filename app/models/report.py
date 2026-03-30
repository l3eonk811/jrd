from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Report(Base):
    """User-submitted reports (e.g. listing moderation)."""

    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_target_type_target_id", "target_type", "target_id"),
        Index("ix_reports_status", "status"),
    )

    STATUS_PENDING = "pending"
    STATUS_REVIEWED = "reviewed"
    STATUS_ACTION_TAKEN = "action_taken"
    STATUS_DISMISSED = "dismissed"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type = Column(String(32), nullable=False, default="listing")
    target_id = Column(Integer, nullable=False)
    reason = Column(String(100), nullable=False)
    note = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default=STATUS_PENDING)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    reporter = relationship("User")
