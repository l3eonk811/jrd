from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    # Admin console RBAC when is_admin: super_admin | moderator | support | viewer
    role = Column(String(32), nullable=False, default="viewer", index=True)
    is_blocked = Column(Boolean, default=False, nullable=False)

    # Email verification
    is_email_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String(255), nullable=True, unique=True, index=True)
    verification_token_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Location
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Profile fields (added migration 0013)
    display_name = Column(String(100), nullable=True)
    bio = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    phone_number = Column(String(30), nullable=True)   # PRIVATE — never exposed unless allowed
    allow_messages_default = Column(Boolean, nullable=False, default=True)
    allow_phone_default = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    items = relationship("Item", back_populates="owner", cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
