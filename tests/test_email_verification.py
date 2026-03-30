"""
Tests for email verification functionality.

Tests:
- Token generation and uniqueness
- Successful verification flow
- Expired token rejection
- Already verified user behavior
- Verification enforcement on public items
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import email_verification_service
from app.services.item_service import create_item
from app.schemas.item import ItemCreate, ListingType


@pytest.fixture
def unverified_user(db: Session) -> User:
    """Create an unverified user."""
    user = User(
        email="unverified@test.com",
        username="unverified",
        hashed_password="fake_hash",
        is_email_verified=False
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def verified_user(db: Session) -> User:
    """Create a verified user."""
    user = User(
        email="verified@test.com",
        username="verified",
        hashed_password="fake_hash",
        is_email_verified=True,
        latitude=40.7128,
        longitude=-74.0060
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestTokenGeneration:
    """Test verification token generation."""

    def test_generate_token_creates_unique_token(self):
        """Tokens should be unique."""
        token1 = email_verification_service.generate_verification_token()
        token2 = email_verification_service.generate_verification_token()
        
        assert token1 != token2
        assert len(token1) > 20  # Should be reasonably long

    def test_create_verification_token_stores_token(self, db: Session, unverified_user: User):
        """Creating a token should store it on the user."""
        token = email_verification_service.create_verification_token(db, unverified_user)
        
        db.refresh(unverified_user)
        
        assert unverified_user.verification_token == token
        assert unverified_user.verification_token_expires_at is not None
        
        # Token should expire in the future
        assert unverified_user.verification_token_expires_at > datetime.utcnow()


class TestEmailVerification:
    """Test email verification flow."""

    def test_successful_verification(self, db: Session, unverified_user: User):
        """Valid token should verify email."""
        token = email_verification_service.create_verification_token(db, unverified_user)
        
        verified_user = email_verification_service.verify_email_token(db, token)
        
        assert verified_user.is_email_verified is True
        assert verified_user.verification_token is None
        assert verified_user.verification_token_expires_at is None

    def test_invalid_token_rejected(self, db: Session):
        """Invalid token should raise error."""
        with pytest.raises(Exception) as exc_info:
            email_verification_service.verify_email_token(db, "invalid-token-12345")
        
        assert "invalid" in str(exc_info.value).lower() or "expired" in str(exc_info.value).lower()

    def test_expired_token_rejected(self, db: Session, unverified_user: User):
        """Expired token should be rejected."""
        token = email_verification_service.create_verification_token(db, unverified_user)
        
        # Manually expire the token
        unverified_user.verification_token_expires_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
        
        with pytest.raises(Exception) as exc_info:
            email_verification_service.verify_email_token(db, token)
        
        assert "expired" in str(exc_info.value).lower()

    def test_already_verified_user_rejected(self, db: Session, verified_user: User):
        """Verifying an already verified user should raise error."""
        # Create a token for an already verified user
        token = email_verification_service.generate_verification_token()
        verified_user.verification_token = token
        verified_user.verification_token_expires_at = datetime.utcnow() + timedelta(hours=24)
        db.commit()
        
        with pytest.raises(Exception) as exc_info:
            email_verification_service.verify_email_token(db, token)
        
        assert "already verified" in str(exc_info.value).lower()


class TestRequestVerificationEmail:
    """Test requesting verification emails."""

    def test_request_verification_creates_token(self, db: Session, unverified_user: User):
        """Requesting verification should create a new token."""
        email_verification_service.request_verification_email(db, unverified_user)
        
        db.refresh(unverified_user)
        
        assert unverified_user.verification_token is not None
        assert unverified_user.verification_token_expires_at is not None

    def test_already_verified_cannot_request(self, db: Session, verified_user: User):
        """Already verified users cannot request new verification."""
        with pytest.raises(Exception) as exc_info:
            email_verification_service.request_verification_email(db, verified_user)
        
        assert "already verified" in str(exc_info.value).lower()


class TestVerificationEnforcement:
    """Test that verification is enforced where required."""

    @patch("app.config.get_settings")
    def test_unverified_cannot_create_public_item(
        self, mock_get_settings, db: Session, unverified_user: User
    ):
        """Unverified users cannot create public items when verification is enabled."""
        mock_get_settings.return_value = MagicMock(email_verification_enabled=True)
        item_data = ItemCreate(
            title="Test Item",
            description="Test",
            condition="good",
            listing_type=ListingType.donation,
            is_public=True,
            latitude=40.7128,
            longitude=-74.0060
        )
        
        with pytest.raises(Exception) as exc_info:
            create_item(db, item_data, unverified_user)
        
        assert "verification" in str(exc_info.value).lower()

    def test_unverified_can_create_private_item(self, db: Session, unverified_user: User):
        """Unverified users CAN create private items."""
        item_data = ItemCreate(
            title="Private Test Item",
            description="Test",
            condition="good",
            listing_type=ListingType.donation,
            is_public=False
        )
        
        # Should succeed
        item = create_item(db, item_data, unverified_user)
        assert item.title == "Private Test Item"
        assert item.is_public is False

    def test_verified_can_create_public_item(self, db: Session, verified_user: User):
        """Verified users CAN create public items."""
        item_data = ItemCreate(
            title="Public Test Item",
            description="Test",
            condition="good",
            listing_type=ListingType.donation,
            is_public=True,
            latitude=40.7128,
            longitude=-74.0060
        )
        
        # Should succeed
        item = create_item(db, item_data, verified_user)
        assert item.title == "Public Test Item"
        assert item.is_public is True


class TestRequireVerifiedEmail:
    """Test the require_verified_email helper."""

    def test_verified_user_passes(self, verified_user: User):
        """Verified user should pass check."""
        # Should not raise
        email_verification_service.require_verified_email(verified_user)

    @patch("app.config.get_settings")
    def test_unverified_user_fails(self, mock_get_settings, unverified_user: User):
        """Unverified user should fail check when verification is enabled."""
        mock_get_settings.return_value = MagicMock(email_verification_enabled=True)
        with pytest.raises(Exception) as exc_info:
            email_verification_service.require_verified_email(unverified_user)

        assert "verification" in str(exc_info.value).lower()
