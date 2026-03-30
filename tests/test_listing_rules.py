"""
Tests for the Phase 1 product expansion:
- listing_domain + listing_type business rules
- price rules (sale required, donation/adoption forbidden)
- adoption fields validation and persistence
- service fields validation and persistence
- phone visibility rules
- favorites save/unsave
- messaging rules (own listing, inactive listing, allow_messages)
- listing_domain filters in search
"""
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.item import Item, ItemStatus, AdoptionDetails, ServiceDetails, Favorite
from app.models.messaging import Conversation, Message
from app.schemas.item import (
    ItemCreate, AdoptionDetailsCreate, ServiceDetailsCreate, _validate_listing_business_rules,
)
from app.models.item import ListingDomain, ListingType, PricingModel
from app.services import item_service, favorites_service, conversation_service


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def user_a(db: Session) -> User:
    u = User(email="a@test.com", username="user_a", hashed_password="x",
             is_email_verified=True, latitude=24.7, longitude=46.7)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def user_b(db: Session) -> User:
    u = User(email="b@test.com", username="user_b", hashed_password="x",
             is_email_verified=True, latitude=24.71, longitude=46.71)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def sale_item(db: Session, user_a: User) -> Item:
    item = Item(
        user_id=user_a.id, title="Laptop for sale",
        listing_domain="item", listing_type="sale",
        price=500.0, currency="SAR",
        status=ItemStatus.available.value, is_public=True,
        latitude=24.7, longitude=46.7, allow_messages=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture
def donation_item(db: Session, user_a: User) -> Item:
    item = Item(
        user_id=user_a.id, title="Free table",
        listing_domain="item", listing_type="donation",
        price=None, currency="SAR",
        status=ItemStatus.available.value, is_public=True,
        latitude=24.7, longitude=46.7, allow_messages=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture
def adoption_item(db: Session, user_a: User) -> Item:
    item = Item(
        user_id=user_a.id, title="Cat for adoption",
        listing_domain="item", listing_type="adoption",
        price=None, currency="SAR",
        status=ItemStatus.available.value, is_public=True,
        latitude=24.7, longitude=46.7, allow_messages=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    adoption = AdoptionDetails(
        item_id=item.id, animal_type="Cat", age="2 years",
        gender="female", vaccinated_status="vaccinated",
        neutered_status="neutered", special_experience_required=False,
    )
    db.add(adoption)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture
def service_item(db: Session, user_a: User) -> Item:
    item = Item(
        user_id=user_a.id, title="Plumber available",
        listing_domain="service", listing_type=None,
        service_category="plumber",
        price=150.0, currency="SAR",
        status=ItemStatus.available.value, is_public=True,
        latitude=24.7, longitude=46.7, allow_messages=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    svc = ServiceDetails(
        item_id=item.id, service_category="plumber",
        pricing_model="fixed", service_mode="at_client_location",
        service_area="Riyadh", experience_years=5,
    )
    db.add(svc)
    db.commit()
    db.refresh(item)
    return item


# ── Price rule tests ──────────────────────────────────────────────────────────

class TestPriceRules:
    def test_sale_requires_price(self):
        with pytest.raises(ValueError, match="Price is required"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.item,
                listing_type=ListingType.sale,
                price=None,
            )

    def test_sale_requires_positive_price(self):
        with pytest.raises(ValueError, match="Price is required"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.item,
                listing_type=ListingType.sale,
                price=0,
            )

    def test_sale_with_valid_price_passes(self):
        # Should not raise
        _validate_listing_business_rules(
            listing_domain=ListingDomain.item,
            listing_type=ListingType.sale,
            price=100.0,
        )

    def test_donation_forbids_price(self):
        with pytest.raises(ValueError, match="Price must be null"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.item,
                listing_type=ListingType.donation,
                price=10.0,
            )

    def test_donation_with_no_price_passes(self):
        _validate_listing_business_rules(
            listing_domain=ListingDomain.item,
            listing_type=ListingType.donation,
            price=None,
        )

    def test_adoption_forbids_price(self):
        with pytest.raises(ValueError, match="Price must be null"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.item,
                listing_type=ListingType.adoption,
                price=50.0,
                adoption_details=AdoptionDetailsCreate(animal_type="Dog"),
            )

    def test_service_allows_price(self):
        _validate_listing_business_rules(
            listing_domain=ListingDomain.service,
            listing_type=None,
            price=200.0,
            service_details=ServiceDetailsCreate(service_category="plumber"),
        )

    def test_service_allows_null_price(self):
        _validate_listing_business_rules(
            listing_domain=ListingDomain.service,
            listing_type=None,
            price=None,
            service_details=ServiceDetailsCreate(service_category="plumber"),
        )


# ── Adoption tests ────────────────────────────────────────────────────────────

class TestAdoptionFields:
    def test_adoption_requires_adoption_details(self):
        with pytest.raises(ValueError, match="adoption_details are required"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.item,
                listing_type=ListingType.adoption,
                price=None,
                adoption_details=None,
            )

    def test_adoption_details_persisted(self, db: Session, adoption_item: Item):
        """Adoption details are stored in a separate table linked to item."""
        details = db.query(AdoptionDetails).filter(
            AdoptionDetails.item_id == adoption_item.id
        ).first()
        assert details is not None
        assert details.animal_type == "Cat"
        assert details.vaccinated_status == "vaccinated"

    def test_non_adoption_cannot_have_adoption_details(self):
        with pytest.raises(ValueError, match="adoption_details can only be set on adoption"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.item,
                listing_type=ListingType.sale,
                price=100.0,
                adoption_details=AdoptionDetailsCreate(animal_type="Dog"),
            )

    def test_service_cannot_have_adoption_details(self):
        with pytest.raises(ValueError, match="adoption_details cannot be set on service"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.service,
                listing_type=None,
                price=None,
                service_details=ServiceDetailsCreate(service_category="other"),
                adoption_details=AdoptionDetailsCreate(animal_type="Dog"),
            )


# ── Service tests ─────────────────────────────────────────────────────────────

class TestServiceFields:
    def test_service_requires_service_details(self):
        with pytest.raises(ValueError, match="service_details are required"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.service,
                listing_type=None,
                price=None,
                service_details=None,
            )

    def test_service_forbids_listing_type(self):
        with pytest.raises(ValueError, match="listing_type must be null for service"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.service,
                listing_type=ListingType.sale,
                price=None,
                service_details=ServiceDetailsCreate(service_category="other"),
            )

    def test_service_details_persisted(self, db: Session, service_item: Item):
        details = db.query(ServiceDetails).filter(
            ServiceDetails.item_id == service_item.id
        ).first()
        assert details is not None
        assert details.service_category == "plumber"
        assert service_item.service_category == "plumber"
        assert details.pricing_model == "fixed"
        assert details.experience_years == 5

    def test_item_cannot_have_service_details(self):
        with pytest.raises(ValueError, match="service_details cannot be set on item"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.item,
                listing_type=ListingType.sale,
                price=100.0,
                service_details=ServiceDetailsCreate(service_category="plumber"),
            )


# ── Listing domain: item requires listing_type ────────────────────────────────

class TestListingDomainRules:
    def test_item_domain_requires_listing_type(self):
        with pytest.raises(ValueError, match="listing_type is required for item"):
            _validate_listing_business_rules(
                listing_domain=ListingDomain.item,
                listing_type=None,
                price=None,
            )


# ── Phone visibility tests ────────────────────────────────────────────────────

class TestPhoneVisibilityRules:
    def test_phone_not_shown_by_default(self, db: Session, user_a: User, sale_item: Item):
        user_a.phone_number = "+966501234567"
        sale_item.show_phone_in_listing = False
        db.commit()
        db.refresh(user_a)
        db.refresh(sale_item)
        # Reload item so owner relationship is available
        sale_item.owner = user_a
        info = item_service.build_seller_info(sale_item)
        assert info["phone_number"] is None

    def test_phone_shown_when_allowed(self, db: Session, user_a: User, sale_item: Item):
        user_a.phone_number = "+966501234567"
        sale_item.show_phone_in_listing = True
        db.commit()
        db.refresh(user_a)
        db.refresh(sale_item)
        sale_item.owner = user_a
        info = item_service.build_seller_info(sale_item)
        assert info["phone_number"] == "+966501234567"

    def test_phone_not_shown_when_user_has_no_phone(self, db: Session, user_a: User, sale_item: Item):
        user_a.phone_number = None
        sale_item.show_phone_in_listing = True  # flag is set but no number exists
        db.commit()
        db.refresh(user_a)
        db.refresh(sale_item)
        sale_item.owner = user_a
        info = item_service.build_seller_info(sale_item)
        assert info["phone_number"] is None


# ── Favorites tests ───────────────────────────────────────────────────────────

class TestFavorites:
    def test_favorite_and_unfavorite(self, db: Session, user_b: User, sale_item: Item):
        result = favorites_service.toggle_favorite(db, user_b.id, sale_item.id)
        assert result["favorited"] is True
        assert result["item_id"] == sale_item.id

        result2 = favorites_service.toggle_favorite(db, user_b.id, sale_item.id)
        assert result2["favorited"] is False

    def test_no_duplicate_favorites(self, db: Session, user_b: User, sale_item: Item):
        favorites_service.toggle_favorite(db, user_b.id, sale_item.id)
        assert favorites_service.is_favorited(db, user_b.id, sale_item.id) is True
        # Toggle again removes it
        favorites_service.toggle_favorite(db, user_b.id, sale_item.id)
        assert favorites_service.is_favorited(db, user_b.id, sale_item.id) is False

    def test_get_user_favorites(self, db: Session, user_b: User, sale_item: Item, donation_item: Item):
        favorites_service.toggle_favorite(db, user_b.id, sale_item.id)
        favorites_service.toggle_favorite(db, user_b.id, donation_item.id)
        favs = favorites_service.get_user_favorites(db, user_b.id, limit=100)
        fav_ids = [item.id for item in favs]
        assert sale_item.id in fav_ids
        assert donation_item.id in fav_ids

    def test_favorite_nonexistent_item_raises(self, db: Session, user_b: User):
        with pytest.raises(HTTPException) as exc_info:
            favorites_service.toggle_favorite(db, user_b.id, 99999)
        assert exc_info.value.status_code == 404


# ── Messaging tests ───────────────────────────────────────────────────────────

class TestMessagingRules:
    def test_cannot_message_own_listing(self, db: Session, user_a: User, sale_item: Item):
        with pytest.raises(HTTPException) as exc_info:
            conversation_service.get_or_create_conversation(
                db, item_id=sale_item.id,
                interested_user_id=user_a.id,  # same as owner
                initial_message="Hello!",
            )
        assert exc_info.value.status_code == 400
        assert "own listing" in str(exc_info.value.detail).lower()

    def test_cannot_message_archived_listing(self, db: Session, user_a: User, user_b: User):
        archived = Item(
            user_id=user_a.id, title="Old item",
            listing_domain="item", listing_type="sale", price=100.0,
            status=ItemStatus.archived.value, is_public=True,
            latitude=24.7, longitude=46.7, allow_messages=True,
        )
        db.add(archived)
        db.commit()
        db.refresh(archived)
        with pytest.raises(HTTPException) as exc_info:
            conversation_service.get_or_create_conversation(
                db, item_id=archived.id,
                interested_user_id=user_b.id,
                initial_message="Can I have it?",
            )
        assert exc_info.value.status_code == 400

    def test_cannot_message_when_allow_messages_false(self, db: Session, user_a: User, user_b: User):
        item = Item(
            user_id=user_a.id, title="No messages allowed",
            listing_domain="item", listing_type="sale", price=200.0,
            status=ItemStatus.available.value, is_public=True,
            latitude=24.7, longitude=46.7, allow_messages=False,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        with pytest.raises(HTTPException) as exc_info:
            conversation_service.get_or_create_conversation(
                db, item_id=item.id,
                interested_user_id=user_b.id,
                initial_message="Interested",
            )
        assert exc_info.value.status_code == 400
        assert "does not accept messages" in str(exc_info.value.detail).lower()

    def test_successful_conversation_created(self, db: Session, user_a: User, user_b: User, sale_item: Item):
        conv = conversation_service.get_or_create_conversation(
            db, item_id=sale_item.id,
            interested_user_id=user_b.id,
            initial_message="Is this still available?",
        )
        assert conv is not None
        assert conv.item_id == sale_item.id
        assert conv.owner_user_id == user_a.id
        assert conv.interested_user_id == user_b.id
        assert len(conv.messages) == 1
        assert conv.messages[0].body == "Is this still available?"

    def test_second_message_adds_to_same_conversation(self, db: Session, user_a: User, user_b: User, sale_item: Item):
        conv1 = conversation_service.get_or_create_conversation(
            db, item_id=sale_item.id,
            interested_user_id=user_b.id,
            initial_message="First message",
        )
        conv2 = conversation_service.get_or_create_conversation(
            db, item_id=sale_item.id,
            interested_user_id=user_b.id,
            initial_message="Second message",
        )
        assert conv1.id == conv2.id
        assert len(conv2.messages) == 2

    def test_owner_can_reply(self, db: Session, user_a: User, user_b: User, sale_item: Item):
        conv = conversation_service.get_or_create_conversation(
            db, item_id=sale_item.id,
            interested_user_id=user_b.id,
            initial_message="Hello",
        )
        msg = conversation_service.send_message(db, conv.id, user_a.id, "Yes it is!")
        assert msg.sender_user_id == user_a.id
        assert msg.body == "Yes it is!"

    def test_non_participant_cannot_send(self, db: Session, user_a: User, user_b: User, sale_item: Item):
        conv = conversation_service.get_or_create_conversation(
            db, item_id=sale_item.id,
            interested_user_id=user_b.id,
            initial_message="Hi",
        )
        stranger = User(email="c@test.com", username="stranger", hashed_password="x")
        db.add(stranger)
        db.commit()
        db.refresh(stranger)
        with pytest.raises(HTTPException) as exc_info:
            conversation_service.send_message(db, conv.id, stranger.id, "Intrude!")
        assert exc_info.value.status_code == 403


# ── Published date in response ────────────────────────────────────────────────

class TestListingDates:
    def test_sale_item_has_created_at(self, db: Session, sale_item: Item):
        assert sale_item.created_at is not None

    def test_adoption_item_has_created_at(self, db: Session, adoption_item: Item):
        assert adoption_item.created_at is not None

    def test_service_item_has_created_at(self, db: Session, service_item: Item):
        assert service_item.created_at is not None
