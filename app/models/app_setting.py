from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class AppSetting(Base):
    """Key/value application settings and feature flags (value is string or JSON text)."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(500), nullable=True)
    # server_default + onupdate for raw SQL; application code also sets updated_at in settings_service.set_setting
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
