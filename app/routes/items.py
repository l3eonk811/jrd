import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.item import ListingDomain
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate, SellerInfo
from app.schemas.provider_ratings import ProviderRatingSummary, ViewerProviderRating
from app.services.auth_service import get_current_user, get_optional_current_user
from app.services import item_service
from app.services import provider_rating_service as prs
from app.services.favorites_service import is_favorited, get_favorited_item_ids_for_items
from app.domain.listing_lifecycle import canonical_listing_lifecycle

router = APIRouter(prefix="/api/items", tags=["items"])


def _enrich_item(item, current_user_id: Optional[int], db: Session) -> ItemRead:
    """Attach seller info and is_favorited to the item before serialising."""
    seller = item_service.build_seller_info(item)
    faved = is_favorited(db, current_user_id, item.id) if current_user_id else None
    data = ItemRead.model_validate(item)
    data.listing_lifecycle = canonical_listing_lifecycle(str(item.status), bool(item.is_public))
    data.seller = SellerInfo(**seller)
    data.is_favorited = faved
    if item.listing_domain == ListingDomain.service.value:
        avg, cnt = prs.get_rating_summary(db, item.user_id)
        data.provider_rating_summary = ProviderRatingSummary(average_rating=avg, rating_count=cnt)
        if current_user_id:
            mine = prs.get_rater_rating(db, current_user_id, item.user_id)
            if mine:
                data.viewer_provider_rating = ViewerProviderRating(
                    stars=mine.stars,
                    comment=mine.comment,
                    updated_at=mine.updated_at,
                )
    return data


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(
    payload: ItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = item_service.create_item(db, payload, current_user)
    return _enrich_item(item, current_user.id, db)


ALLOWED_STATUS_BUCKETS = frozenset({"all", "active", "draft", "reserved", "donated", "archived"})


@router.get("", response_model=PaginatedResponse[ItemRead])
def list_my_items(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_bucket: str = Query(default="all", description="Filter: all|active|draft|reserved|donated|archived"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bucket = status_bucket.strip().lower() if status_bucket else "all"
    if bucket not in ALLOWED_STATUS_BUCKETS:
        bucket = "all"
    items, total_count = item_service.get_user_items(
        db, current_user.id, page=page, page_size=page_size, status_bucket=bucket
    )
    fav_ids = get_favorited_item_ids_for_items(db, current_user.id, [i.id for i in items])
    enriched = []
    for item in items:
        seller = item_service.build_seller_info(item)
        data = ItemRead.model_validate(item)
        data.listing_lifecycle = canonical_listing_lifecycle(str(item.status), bool(item.is_public))
        data.seller = SellerInfo(**seller)
        data.is_favorited = item.id in fav_ids
        enriched.append(data)

    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
    return PaginatedResponse(
        items=enriched,
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
    )


@router.get("/{item_id}", response_model=ItemRead)
def get_item(
    item_id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    item = item_service.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not item.is_public:
        if current_user is None or item.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

    is_owner = current_user is not None and item.user_id == current_user.id
    if item.is_public and not is_owner:
        try:
            db.query(item.__class__).filter(item.__class__.id == item_id).update(
                {"view_count": item.__class__.view_count + 1}
            )
            db.commit()
            item.view_count = (item.view_count or 0) + 1
        except Exception:
            db.rollback()

    return _enrich_item(item, current_user.id if current_user else None, db)


@router.patch("/{item_id}", response_model=ItemRead)
def update_item(
    item_id: int,
    payload: ItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = item_service.update_item(db, item_id, payload, current_user)
    return _enrich_item(item, current_user.id, db)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item_service.delete_item(db, item_id, current_user)
