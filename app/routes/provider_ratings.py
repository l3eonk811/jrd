import math
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.provider_ratings import (
    ProviderActiveServiceListingRead,
    ProviderProfileRead,
    ProviderPublicCard,
    ProviderRatingSummary,
    ProviderRatingUpsert,
    ProviderRatingUpsertResult,
    ProviderReviewRead,
)
from app.services.auth_service import get_current_user
from app.services import provider_rating_service as prs

router = APIRouter(tags=["provider-ratings"])


@router.post("/api/me/provider-ratings", response_model=ProviderRatingUpsertResult)
def upsert_my_provider_rating(
    payload: ProviderRatingUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = prs.upsert_rating(
        db,
        rater_user_id=current_user.id,
        provider_user_id=payload.provider_user_id,
        stars=payload.stars,
        comment=payload.comment,
    )
    return ProviderRatingUpsertResult(
        provider_user_id=row.provider_user_id,
        stars=row.stars,
        comment=row.comment,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/api/users/{user_id}/provider-profile", response_model=ProviderProfileRead)
def get_provider_profile(
    user_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    provider = db.query(User).filter(User.id == user_id).first()
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not prs.provider_profile_eligible(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not a service provider profile",
        )

    avg, count = prs.get_rating_summary(db, user_id)
    review_rows, total_reviews = prs.list_reviews_paginated(db, user_id, page=page, page_size=page_size)
    reviews_out = [
        ProviderReviewRead(
            stars=r.stars,
            comment=r.comment,
            reviewer_display=prs.reviewer_display(u),
            created_at=r.created_at,
        )
        for r, u in review_rows
    ]
    total_pages = max(1, math.ceil(total_reviews / page_size)) if total_reviews else 1

    items = prs.list_active_public_service_items(db, user_id)
    listings_out = [
        ProviderActiveServiceListingRead(
            id=it.id,
            title=it.title,
            price=it.price,
            currency=it.currency or "SAR",
            primary_image_url=prs.primary_image_url(it),
        )
        for it in items
    ]

    return ProviderProfileRead(
        provider=ProviderPublicCard(
            id=provider.id,
            username=provider.username,
            display_name=provider.display_name,
            city=provider.city,
        ),
        rating_summary=ProviderRatingSummary(average_rating=avg, rating_count=count),
        reviews=PaginatedResponse(
            items=reviews_out,
            page=page,
            page_size=page_size,
            total_count=total_reviews,
            total_pages=total_pages,
        ),
        active_service_listings=listings_out,
    )
