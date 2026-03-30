from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class ProviderRating(Base):
    """Open model: one rating per rater per service provider user (not tied to listings)."""

    __tablename__ = "provider_ratings"
    __table_args__ = (
        UniqueConstraint("provider_user_id", "rater_user_id", name="uq_provider_ratings_provider_rater"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rater_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stars = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
