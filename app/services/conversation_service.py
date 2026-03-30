from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy import desc, func as sa_func
from sqlalchemy.orm import Session, joinedload, noload
from fastapi import HTTPException, status

from app.models.messaging import Conversation, Message
from app.models.item import Item, ItemStatus
from app.services import block_service
from app.config import get_settings


_INACTIVE_STATUSES = {ItemStatus.archived.value, ItemStatus.removed.value}


def _load_options():
    """Full thread load (admin, post-create) — includes all messages."""
    return [
        joinedload(Conversation.messages).joinedload(Message.sender),
        joinedload(Conversation.item),
        joinedload(Conversation.owner),
        joinedload(Conversation.interested_user),
    ]


def _load_options_shell():
    """Participant + listing context without loading message bodies (inbox list)."""
    return [
        noload(Conversation.messages),
        joinedload(Conversation.item).options(
            joinedload(Item.images),
            joinedload(Item.service_details),
            joinedload(Item.adoption_details),
        ),
        joinedload(Conversation.owner),
        joinedload(Conversation.interested_user),
    ]


def last_messages_for_conversation_ids(db: Session, conv_ids: List[int]) -> Dict[int, Message]:
    """One message per conversation: the latest by primary key (monotonic with time)."""
    if not conv_ids:
        return {}
    subq = (
        db.query(
            Message.conversation_id,
            sa_func.max(Message.id).label("mid"),
        )
        .filter(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
        .subquery()
    )
    rows = (
        db.query(Message)
        .join(subq, Message.id == subq.c.mid)
        .options(joinedload(Message.sender))
        .all()
    )
    return {m.conversation_id: m for m in rows}


def _other_participant_id(conv: Conversation, sender_id: int) -> int:
    return conv.owner_user_id if sender_id == conv.interested_user_id else conv.interested_user_id


def _assert_sender_may_send(db: Session, sender_id: int, conv: Conversation) -> None:
    other = _other_participant_id(conv, sender_id)
    if block_service.other_participant_blocked_sender(db, sender_id, other):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot send messages in this conversation.",
        )


def get_or_create_conversation(
    db: Session,
    item_id: int,
    interested_user_id: int,
    initial_message: str,
) -> Conversation:
    """
    Find or create the conversation between the interested user and the listing owner.
    Enforces all messaging rules.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")

    # Cannot message own listing
    if item.user_id == interested_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot send a message on your own listing",
        )

    # Listing must be active
    if item.status in _INACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Messaging is not available on archived or removed listings",
        )

    # Listing must allow messages
    if not item.allow_messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This listing does not accept messages",
        )

    if block_service.any_block_between_users(db, item.user_id, interested_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Messaging is not available between these accounts.",
        )

    # Look for existing conversation
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.item_id == item_id,
            Conversation.interested_user_id == interested_user_id,
        )
        .first()
    )

    if not conversation:
        conversation = Conversation(
            item_id=item_id,
            owner_user_id=item.user_id,
            interested_user_id=interested_user_id,
        )
        db.add(conversation)
        db.flush()

    _assert_sender_may_send(db, interested_user_id, conversation)

    # Add the initial (or follow-up) message
    msg = Message(
        conversation_id=conversation.id,
        sender_user_id=interested_user_id,
        body=initial_message.strip(),
        message_kind="text",
        latitude=None,
        longitude=None,
    )
    db.add(msg)
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()

    return _load_conversation(db, conversation.id)


def send_message(
    db: Session,
    conversation_id: int,
    sender_user_id: int,
    body: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Message:
    """Send a text or exact-location message. Either participant may reply unless blocked."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Only participants can send
    if sender_user_id not in (conv.owner_user_id, conv.interested_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant")

    _assert_sender_may_send(db, sender_user_id, conv)

    # Re-check listing is still active
    item = db.query(Item).filter(Item.id == conv.item_id).first()
    if item and item.status in _INACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Listing is no longer active",
        )

    if latitude is not None and longitude is not None:
        msg = Message(
            conversation_id=conversation_id,
            sender_user_id=sender_user_id,
            body=(body or "").strip(),
            message_kind="location_share",
            latitude=latitude,
            longitude=longitude,
        )
    else:
        msg = Message(
            conversation_id=conversation_id,
            sender_user_id=sender_user_id,
            body=body.strip(),
            message_kind="text",
            latitude=None,
            longitude=None,
        )
    db.add(msg)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(msg)
    return msg


def get_conversation(
    db: Session, conversation_id: int, requesting_user_id: int
) -> Conversation:
    conv = _load_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if requesting_user_id not in (conv.owner_user_id, conv.interested_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant")
    return conv


def load_conversation_shell(
    db: Session, conversation_id: int, requesting_user_id: int
) -> Conversation:
    """Participant check + listing/users, no messages (use with sliced message query)."""
    conv = (
        db.query(Conversation)
        .options(*_load_options_shell())
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if requesting_user_id not in (conv.owner_user_id, conv.interested_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant")
    return conv


def fetch_thread_messages(
    db: Session, conversation_id: int, *, limit: int
) -> Tuple[List[Message], int]:
    """Return last ``limit`` messages (oldest-first) and total count in thread."""
    total = (
        db.query(sa_func.count(Message.id))
        .filter(Message.conversation_id == conversation_id)
        .scalar()
        or 0
    )
    rows = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows)), int(total)


def get_user_conversations(db: Session, user_id: int) -> List[Conversation]:
    """All conversations where the user is owner or interested party (no message bodies)."""
    lim = get_settings().conversation_inbox_max_rows
    return (
        db.query(Conversation)
        .options(*_load_options_shell())
        .filter(
            (Conversation.owner_user_id == user_id)
            | (Conversation.interested_user_id == user_id)
        )
        .order_by(Conversation.updated_at.desc())
        .limit(lim)
        .all()
    )


def mark_messages_read(
    db: Session, conversation_id: int, reader_user_id: int
) -> None:
    now = datetime.now(timezone.utc)
    db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.sender_user_id != reader_user_id,
        Message.read_at == None,
    ).update({"read_at": now})
    db.commit()


def _load_conversation(db: Session, conversation_id: int) -> Optional[Conversation]:
    return (
        db.query(Conversation)
        .options(*_load_options())
        .filter(Conversation.id == conversation_id)
        .first()
    )


def get_conversation_for_admin(db: Session, conversation_id: int) -> Conversation:
    """Load full conversation thread without participant check (admin read-only)."""
    conv = _load_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


def list_conversations_for_admin(
    db: Session, *, page: int = 1, page_size: int = 20
) -> Tuple[List[Conversation], int]:
    """Paginated threads for admin console (newest activity first)."""
    q = db.query(Conversation).options(*_load_options_shell())
    total = q.count()
    rows = (
        q.order_by(
            desc(sa_func.coalesce(Conversation.updated_at, Conversation.created_at)),
            desc(Conversation.id),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total
