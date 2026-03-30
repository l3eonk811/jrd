from typing import List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.item import ItemRead, SellerInfo
from app.schemas.favorites import FavoriteToggleResponse
from app.services.auth_service import get_current_user
from app.services import favorites_service, item_service
from app.domain.listing_lifecycle import canonical_listing_lifecycle
from app.config import get_settings

router = APIRouter(prefix="/api/favorites", tags=["favorites"])
_settings = get_settings()


@router.post("/{item_id}", response_model=FavoriteToggleResponse)
def toggle_favorite(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle favorite status for a listing. Works as save/unsave."""
    result = favorites_service.toggle_favorite(db, current_user.id, item_id)
    return result


@router.get("", response_model=List[ItemRead])
def get_saved_listings(
    limit: int = Query(
        default=100,
        ge=1,
        le=_settings.favorites_max_page_size,
        description="Max saved listings to return (most recent first).",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return listings saved/favorited by the current user (bounded, newest first)."""
    items = favorites_service.get_user_favorites(db, current_user.id, limit=limit)
    enriched = []
    for item in items:
        seller = item_service.build_seller_info(item)
        data = ItemRead.model_validate(item)
        data.listing_lifecycle = canonical_listing_lifecycle(str(item.status), bool(item.is_public))
        data.seller = SellerInfo(**seller)
        data.is_favorited = True
        enriched.append(data)
    return enriched
