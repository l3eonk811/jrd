"""
Email verification service.

Handles token generation, validation, and email sending (stubbed for development).
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.user import User


# Token expiration: 24 hours
TOKEN_EXPIRATION_HOURS = 24


def generate_verification_token() -> str:
    """Generate a secure random verification token."""
    return secrets.token_urlsafe(32)


def create_verification_token(db: Session, user: User) -> str:
    """
    Create and store a verification token for the user.
    
    Returns the generated token.
    """
    token = generate_verification_token()
    expires_at = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRATION_HOURS)
    
    user.verification_token = token
    user.verification_token_expires_at = expires_at
    
    db.commit()
    db.refresh(user)
    
    return token


def verify_email_token(db: Session, token: str) -> User:
    """
    Verify an email token and mark the user's email as verified.
    
    Raises HTTPException if token is invalid, expired, or already used.
    Returns the verified user.
    """
    user = db.query(User).filter(User.verification_token == token).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token"
        )
    
    # Check if already verified
    if user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already verified"
        )
    
    # Check expiration
    if user.verification_token_expires_at is None or user.verification_token_expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token has expired. Please request a new one."
        )
    
    # Mark as verified and clear token
    user.is_email_verified = True
    user.verification_token = None
    user.verification_token_expires_at = None
    
    db.commit()
    db.refresh(user)
    
    return user


def send_verification_email(user: User, token: str) -> None:
    """
    Send verification email to user.
    
    In development: logs to console.
    In production: would send actual email via SMTP/SendGrid/SES.
    """
    verification_url = f"http://localhost:3000/verify-email?token={token}"
    
    # Development stub: log to console
    print("\n" + "=" * 80)
    print("📧 EMAIL VERIFICATION")
    print("=" * 80)
    print(f"To: {user.email}")
    print(f"Subject: Verify your email for Nearby Marketplace")
    print()
    print(f"Hi {user.username},")
    print()
    print("Thanks for signing up! Please verify your email by clicking the link below:")
    print()
    print(f"  {verification_url}")
    print()
    print(f"This link will expire in {TOKEN_EXPIRATION_HOURS} hours.")
    print()
    print("If you didn't create an account, you can safely ignore this email.")
    print("=" * 80)
    print()


def request_verification_email(db: Session, user: User) -> None:
    """
    Request a new verification email for a user.
    
    Creates a new token and sends the verification email.
    Raises HTTPException if email is already verified.
    """
    if user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already verified"
        )
    
    # Generate new token
    token = create_verification_token(db, user)
    
    # Send email
    send_verification_email(user, token)


def require_verified_email(user: User, action: str = "perform this action") -> None:
    """
    Require that the user's email is verified.
    
    Raises HTTPException if not verified (unless email_verification_enabled=False in config).
    """
    import logging
    from app.config import get_settings
    
    settings = get_settings()
    logger = logging.getLogger(__name__)
    
    # Bypass check if email verification is disabled
    if not settings.email_verification_enabled:
        logger.debug(
            f"Email verification bypassed for user {user.username} (EMAIL_VERIFICATION_ENABLED=false)"
        )
        return
    
    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Email verification required to {action}. Please check your email for the verification link."
        )
