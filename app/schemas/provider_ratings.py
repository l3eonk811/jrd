from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import PaginatedResponse


class ProviderRatingSummary(BaseModel):
    average_rating: float
    rating_count: int


class ViewerProviderRating(BaseModel):
    """Current user's rating of this provider (service listings only)."""

    stars: int
    comment: Optional[str] = None
    updated_at: Optional[datetime] = None


class ProviderRatingUpsert(BaseModel):
    provider_user_id: int
    stars: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s if s else None


class ProviderRatingUpsertResult(BaseModel):
    provider_user_id: int
    stars: int
    comment: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ProviderReviewRead(BaseModel):
    stars: int
    comment: Optional[str] = None
    reviewer_display: str
    created_at: datetime


class ProviderPublicCard(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    city: Optional[str] = None


class ProviderActiveServiceListingRead(BaseModel):
    id: int
    title: str
    price: Optional[float] = None
    currency: str = "SAR"
    primary_image_url: Optional[str] = None


class ProviderProfileRead(BaseModel):
    provider: ProviderPublicCard
    rating_summary: ProviderRatingSummary
    reviews: PaginatedResponse[ProviderReviewRead]
    active_service_listings: List[ProviderActiveServiceListingRead]
