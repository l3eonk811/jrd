from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.item import Item, ItemImage, ItemStatus, ListingDomain
from app.models.provider_rating import ProviderRating
from app.models.user import User


MAX_COMMENT_LEN = 2000


def user_has_any_service_listing(db: Session, user_id: int) -> bool:
    return (
        db.query(Item.id)
        .filter(
            Item.user_id == user_id,
            Item.listing_domain == ListingDomain.service.value,
        )
        .first()
        is not None
    )


def provider_profile_eligible(db: Session, user_id: int) -> bool:
    """Show provider profile if they have (or had) service context: listing or existing ratings."""
    if user_has_any_service_listing(db, user_id):
        return True
    cnt = (
        db.query(func.count(ProviderRating.id))
        .filter(ProviderRating.provider_user_id == user_id)
        .scalar()
    )
    return bool((cnt or 0) > 0)


def get_rating_summary(db: Session, provider_user_id: int) -> Tuple[float, int]:
    row = (
        db.query(func.avg(ProviderRating.stars), func.count(ProviderRating.id))
        .filter(ProviderRating.provider_user_id == provider_user_id)
        .first()
    )
    if not row or row[1] == 0:
        return 0.0, 0
    avg = float(row[0] or 0)
    return round(avg, 2), int(row[1])


def get_rater_rating(
    db: Session, rater_user_id: int, provider_user_id: int
) -> Optional[ProviderRating]:
    return (
        db.query(ProviderRating)
        .filter(
            ProviderRating.rater_user_id == rater_user_id,
            ProviderRating.provider_user_id == provider_user_id,
        )
        .first()
    )


def upsert_rating(
    db: Session,
    *,
    rater_user_id: int,
    provider_user_id: int,
    stars: int,
    comment: Optional[str],
) -> ProviderRating:
    if rater_user_id == provider_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot rate yourself",
        )
    if not user_has_any_service_listing(db, provider_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a service provider",
        )
    if comment and len(comment) > MAX_COMMENT_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Comment must be at most {MAX_COMMENT_LEN} characters",
        )

    existing = get_rater_rating(db, rater_user_id, provider_user_id)
    now = datetime.now(timezone.utc)
    if existing:
        existing.stars = stars
        existing.comment = comment
        existing.updated_at = now
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    row = ProviderRating(
        provider_user_id=provider_user_id,
        rater_user_id=rater_user_id,
        stars=stars,
        comment=comment,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def reviewer_display(u: User) -> str:
    if u.display_name and u.display_name.strip():
        return u.display_name.strip()
    return u.username


def list_reviews_paginated(
    db: Session, provider_user_id: int, *, page: int, page_size: int
) -> Tuple[List[Tuple[ProviderRating, User]], int]:
    q = (
        db.query(ProviderRating, User)
        .join(User, User.id == ProviderRating.rater_user_id)
        .filter(ProviderRating.provider_user_id == provider_user_id)
        .order_by(ProviderRating.created_at.desc())
    )
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def list_active_public_service_items(db: Session, owner_id: int, limit: int = 50) -> List[Item]:
    return (
        db.query(Item)
        .options(joinedload(Item.images))
        .filter(
            Item.user_id == owner_id,
            Item.listing_domain == ListingDomain.service.value,
            Item.is_public.is_(True),
            Item.status == ItemStatus.available.value,
        )
        .order_by(Item.created_at.desc())
        .limit(limit)
        .all()
    )


def primary_image_url(item: Item) -> Optional[str]:
    imgs = sorted(item.images or [], key=lambda im: (not im.is_primary, im.id))
    if not imgs:
        return None
    return imgs[0].url
