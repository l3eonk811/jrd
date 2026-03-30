from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    email: EmailStr
    username: str


PASSWORD_MAX_BYTES = 72


class UserCreate(UserBase):
    password: str
    full_name: Optional[str] = None   # mapped to display_name
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        raw = (v or "").strip()
        if not raw:
            raise ValueError("Phone number is required")
        digits = "".join(c for c in raw if c.isdigit())
        if len(digits) < 8:
            raise ValueError("Enter a valid phone number (at least 8 digits).")
        if raw.startswith("+"):
            normalized = "+" + digits
        else:
            normalized = digits
        if len(normalized) > 30:
            raise ValueError("Phone number is too long")
        return normalized

    @field_validator("password")
    @classmethod
    def password_validation(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password cannot be empty")
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        if len(v.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(
                f"Password cannot be longer than {PASSWORD_MAX_BYTES} bytes"
            )
        return v


class UserUpdate(BaseModel):
    """Fields users can update on their own profile."""
    username: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = None
    city: Optional[str] = None
    phone_number: Optional[str] = None
    allow_messages_default: Optional[bool] = None
    allow_phone_default: Optional[bool] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-90.0 <= v <= 90.0):
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-180.0 <= v <= 180.0):
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v


class UserRead(UserBase):
    id: int
    is_active: bool
    is_email_verified: bool
    display_name: Optional[str] = None
    bio: Optional[str] = None
    city: Optional[str] = None
    # phone_number intentionally omitted — only shown in listing context when allowed
    allow_messages_default: bool = True
    allow_phone_default: bool = False
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicUserRead(BaseModel):
    """Safe public profile — no phone, no email, no private fields."""
    id: int
    username: str
    display_name: Optional[str] = None
    city: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    """Authenticated user changes their own password (app + admin JWT)."""

    current_password: str
    new_password: str

    @field_validator("current_password")
    @classmethod
    def current_password_not_empty(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("Current password is required")
        return v

    @field_validator("new_password")
    @classmethod
    def new_password_validation(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password cannot be empty")
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        if len(v.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(
                f"Password cannot be longer than {PASSWORD_MAX_BYTES} bytes"
            )
        return v
