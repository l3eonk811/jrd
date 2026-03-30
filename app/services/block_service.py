from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from fastapi import HTTPException, status

from app.models.user import User
from app.models.user_block import UserBlock


def any_block_between_users(db: Session, user_a_id: int, user_b_id: int) -> bool:
    """True if there is any block row between the two users (either direction)."""
    if user_a_id == user_b_id:
        return False
    return (
        db.query(UserBlock)
        .filter(
            or_(
                and_(UserBlock.blocker_id == user_a_id, UserBlock.blocked_id == user_b_id),
                and_(UserBlock.blocker_id == user_b_id, UserBlock.blocked_id == user_a_id),
            )
        )
        .first()
        is not None
    )


def other_participant_blocked_sender(db: Session, sender_id: int, other_user_id: int) -> bool:
    """True if `other_user_id` has blocked `sender_id` (sender may not message)."""
    return (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == other_user_id, UserBlock.blocked_id == sender_id)
        .first()
        is not None
    )


def block_flags_for_viewer(db: Session, viewer_id: int, other_user_id: int) -> tuple[bool, bool, bool]:
    """Returns (you_blocked_them, they_blocked_you, can_send_messages)."""
    you = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == viewer_id, UserBlock.blocked_id == other_user_id)
        .first()
        is not None
    )
    them = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == other_user_id, UserBlock.blocked_id == viewer_id)
        .first()
        is not None
    )
    can_send = not them
    return you, them, can_send


def create_user_block(db: Session, blocker_id: int, blocked_user_id: int) -> UserBlock:
    if blocker_id == blocked_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot block yourself")
    blocked = db.query(User).filter(User.id == blocked_user_id).first()
    if not blocked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    existing = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_user_id)
        .first()
    )
    if existing:
        return existing
    row = UserBlock(blocker_id=blocker_id, blocked_id=blocked_user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_user_block(db: Session, blocker_id: int, blocked_user_id: int) -> bool:
    row = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_user_id)
        .first()
    )
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
