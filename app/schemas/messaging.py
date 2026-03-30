from pydantic import BaseModel, model_validator
from datetime import datetime
from typing import Optional, List, Literal


class MessageCreate(BaseModel):
    body: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @model_validator(mode="after")
    def validate_message_shape(self) -> "MessageCreate":
        has_lat = self.latitude is not None
        has_lon = self.longitude is not None
        if has_lat or has_lon:
            if self.latitude is None or self.longitude is None:
                raise ValueError("latitude and longitude are both required for a location message")
            if not (-90.0 <= self.latitude <= 90.0):
                raise ValueError("latitude must be between -90 and 90")
            if not (-180.0 <= self.longitude <= 180.0):
                raise ValueError("longitude must be between -180 and 180")
            return self
        if not (self.body or "").strip():
            raise ValueError("Message body cannot be empty")
        return self


class MessageRead(BaseModel):
    id: int
    conversation_id: int
    sender_user_id: int
    sender_username: Optional[str] = None
    body: str
    message_kind: Literal["text", "location_share"] = "text"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime
    read_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    item_id: int
    initial_message: str


# ── Listing context sub-schema (shared by list + thread views) ────────────────

class ConversationListingContext(BaseModel):
    """Snapshot of the listing this conversation is about."""
    listing_domain: Optional[str] = None        # "item" | "service"
    listing_type: Optional[str] = None          # "sale" | "donation" | "adoption" | None
    item_primary_image_url: Optional[str] = None
    item_price: Optional[float] = None
    item_currency: Optional[str] = None
    service_category: Optional[str] = None      # populated when domain == "service"
    animal_type: Optional[str] = None           # populated when type == "adoption"


class ConversationRead(BaseModel):
    id: int
    item_id: int
    owner_user_id: int
    interested_user_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    messages: List[MessageRead] = []
    message_count_total: int = 0
    messages_truncated: bool = False

    # Enriched fields
    item_title: Optional[str] = None
    other_user_username: Optional[str] = None
    other_user_display_name: Optional[str] = None
    last_message_body: Optional[str] = None
    last_message_at: Optional[datetime] = None

    # Listing context
    listing_context: Optional[ConversationListingContext] = None

    # Messaging / blocks (viewer = authenticated user loading this conversation)
    can_send_messages: bool = True
    you_blocked_them: bool = False
    they_blocked_you: bool = False

    model_config = {"from_attributes": True}


class ConversationListItem(BaseModel):
    """Lightweight summary for inbox list view."""
    id: int
    item_id: int
    owner_user_id: int
    item_title: Optional[str] = None
    other_user_id: int
    other_user_username: Optional[str] = None
    other_user_display_name: Optional[str] = None
    last_message_body: Optional[str] = None
    last_message_at: Optional[datetime] = None
    created_at: datetime

    can_send_messages: bool = True
    you_blocked_them: bool = False
    they_blocked_you: bool = False

    # Listing context (duplicated flat for easy consumption in list view)
    listing_domain: Optional[str] = None
    listing_type: Optional[str] = None
    item_primary_image_url: Optional[str] = None
    item_price: Optional[float] = None
    item_currency: Optional[str] = None
    service_category: Optional[str] = None
    animal_type: Optional[str] = None

    model_config = {"from_attributes": True}
