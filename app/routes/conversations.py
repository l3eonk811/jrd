from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.messaging import Message
from app.schemas.messaging import (
    ConversationCreate,
    ConversationRead,
    ConversationListItem,
    ConversationListingContext,
    MessageCreate,
    MessageRead,
)
from app.services.auth_service import get_current_user
from app.services import conversation_service, block_service
from app.config import get_settings

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
_settings = get_settings()


def _build_listing_context(item) -> Optional[ConversationListingContext]:
    """Extract a compact listing snapshot from a loaded Item ORM object."""
    if item is None:
        return None

    primary_img = None
    if item.images:
        primary_img = next((img for img in item.images if img.is_primary), item.images[0])

    service_category = None
    if item.service_details:
        service_category = item.service_details.service_category

    animal_type = None
    if item.adoption_details:
        animal_type = item.adoption_details.animal_type

    return ConversationListingContext(
        listing_domain=item.listing_domain,
        listing_type=item.listing_type,
        item_primary_image_url=primary_img.url if primary_img else None,
        item_price=item.price,
        item_currency=item.currency,
        service_category=service_category,
        animal_type=animal_type,
    )


def _is_location_message(m: Message) -> bool:
    return (getattr(m, "message_kind", None) or "text") == "location_share"


def _last_message_preview(m: Message) -> str:
    if _is_location_message(m):
        return "📍 Shared exact location"
    return m.body


def _serialize_message(m: Message) -> MessageRead:
    is_loc = _is_location_message(m)
    return MessageRead(
        id=m.id,
        conversation_id=m.conversation_id,
        sender_user_id=m.sender_user_id,
        sender_username=m.sender.username if m.sender else None,
        body=m.body,
        message_kind="location_share" if is_loc else "text",
        latitude=m.latitude if is_loc else None,
        longitude=m.longitude if is_loc else None,
        created_at=m.created_at,
        read_at=m.read_at,
    )


def _serialize_conversation(
    db: Session,
    conv,
    current_user_id: int,
    *,
    messages: Optional[List[Message]] = None,
    message_count_total: Optional[int] = None,
) -> ConversationRead:
    """Build ConversationRead with enriched display fields."""
    raw_messages = messages if messages is not None else list(conv.messages)
    total = message_count_total if message_count_total is not None else len(raw_messages)
    msgs = [_serialize_message(m) for m in raw_messages]
    last_msg = raw_messages[-1] if raw_messages else None
    other_user = (
        conv.owner if conv.interested_user_id == current_user_id else conv.interested_user
    )
    other_id = other_user.id if other_user else 0
    you_block, they_block, can_send = block_service.block_flags_for_viewer(
        db, current_user_id, other_id
    )
    return ConversationRead(
        id=conv.id,
        item_id=conv.item_id,
        owner_user_id=conv.owner_user_id,
        interested_user_id=conv.interested_user_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=msgs,
        message_count_total=total,
        messages_truncated=total > len(raw_messages),
        item_title=conv.item.title if conv.item else None,
        other_user_username=other_user.username if other_user else None,
        other_user_display_name=getattr(other_user, "display_name", None) if other_user else None,
        last_message_body=_last_message_preview(last_msg) if last_msg else None,
        last_message_at=last_msg.created_at if last_msg else None,
        listing_context=_build_listing_context(conv.item),
        can_send_messages=can_send,
        you_blocked_them=you_block,
        they_blocked_you=they_block,
    )


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def start_or_continue_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a conversation on a listing (or send a message if conversation exists)."""
    conv = conversation_service.get_or_create_conversation(
        db,
        item_id=payload.item_id,
        interested_user_id=current_user.id,
        initial_message=payload.initial_message,
    )
    return _serialize_conversation(db, conv, current_user.id)


@router.get("", response_model=List[ConversationListItem])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Inbox: all conversations where the current user is a participant."""
    convs = conversation_service.get_user_conversations(db, current_user.id)
    last_by = conversation_service.last_messages_for_conversation_ids(db, [c.id for c in convs])
    result = []
    for conv in convs:
        last_msg = last_by.get(conv.id)
        other_user = (
            conv.owner if conv.interested_user_id == current_user.id else conv.interested_user
        )
        other_id = other_user.id if other_user else 0
        you_block, they_block, can_send = block_service.block_flags_for_viewer(
            db, current_user.id, other_id
        )

        item = conv.item
        primary_img = None
        service_category = None
        animal_type = None
        if item:
            if item.images:
                primary_img = next(
                    (img for img in item.images if img.is_primary), item.images[0]
                )
            if item.service_details:
                service_category = item.service_details.service_category
            if item.adoption_details:
                animal_type = item.adoption_details.animal_type

        result.append(
            ConversationListItem(
                id=conv.id,
                item_id=conv.item_id,
                owner_user_id=conv.owner_user_id,
                item_title=item.title if item else None,
                other_user_id=other_id,
                other_user_username=other_user.username if other_user else None,
                other_user_display_name=getattr(other_user, "display_name", None)
                if other_user
                else None,
                last_message_body=_last_message_preview(last_msg) if last_msg else None,
                last_message_at=last_msg.created_at if last_msg else None,
                created_at=conv.created_at,
                can_send_messages=can_send,
                you_blocked_them=you_block,
                they_blocked_you=they_block,
                listing_domain=item.listing_domain if item else None,
                listing_type=item.listing_type if item else None,
                item_primary_image_url=primary_img.url if primary_img else None,
                item_price=item.price if item else None,
                item_currency=item.currency if item else None,
                service_category=service_category,
                animal_type=animal_type,
            )
        )
    return result


@router.get("/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: int,
    messages_limit: int = Query(
        default=120,
        ge=1,
        le=_settings.conversation_messages_max_limit,
        description="Last N messages (newest window).",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = conversation_service.load_conversation_shell(db, conversation_id, current_user.id)
    conversation_service.mark_messages_read(db, conversation_id, current_user.id)
    msg_rows, total = conversation_service.fetch_thread_messages(
        db, conversation_id, limit=messages_limit
    )
    return _serialize_conversation(
        db, conv, current_user.id, messages=msg_rows, message_count_total=total
    )


@router.post("/{conversation_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
def send_message(
    conversation_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = conversation_service.send_message(
        db,
        conversation_id,
        current_user.id,
        payload.body,
        payload.latitude,
        payload.longitude,
    )
    is_loc = _is_location_message(msg)
    return MessageRead(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_user_id=msg.sender_user_id,
        sender_username=current_user.username,
        body=msg.body,
        message_kind="location_share" if is_loc else "text",
        latitude=msg.latitude if is_loc else None,
        longitude=msg.longitude if is_loc else None,
        created_at=msg.created_at,
        read_at=msg.read_at,
    )
