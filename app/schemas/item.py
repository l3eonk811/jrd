from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from typing import Optional, List
from datetime import datetime
from app.models.item import (
    ItemCondition, ItemStatus, ListingDomain, ListingType, PricingModel, ServiceMode
)
from app.domain.listing_lifecycle import CanonicalListingLifecycle
from app.schemas.tag import TagRead
from app.schemas.provider_ratings import ProviderRatingSummary, ViewerProviderRating


# ── Sub-schemas ──────────────────────────────────────────────────────────────

class ItemImageRead(BaseModel):
    id: int
    url: str
    is_primary: bool
    model_config = {"from_attributes": True}


class AIAnalysisRead(BaseModel):
    """Snapshot from optional image analysis. Product AI scope: tags/classification only — not auto titles or blurbs."""

    id: int
    suggested_title: str = Field(
        ...,
        description="Legacy DB column; not used to generate listing titles in active flows.",
    )
    suggested_category: str
    suggested_subcategory: Optional[str] = None
    suggested_condition: str
    suggested_tags: List[str] = Field(
        ...,
        description="Tag/classification output aligned with current AI scope.",
    )
    suggested_description: Optional[str] = Field(
        None,
        description="Legacy; no auto-description generation in active product flows.",
    )
    confidence: float
    ai_service: str
    category_confidence: Optional[float] = None
    subcategory_confidence: Optional[float] = None
    used_fallback: bool = False
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    image_size_bytes: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def ai_backend_used(self) -> str:
        return self.ai_service

    @computed_field
    @property
    def overall_confidence(self) -> float:
        return self.confidence


# ── Adoption schemas ──────────────────────────────────────────────────────────

class AdoptionDetailsBase(BaseModel):
    animal_type: str
    age: Optional[str] = None
    gender: Optional[str] = None          # male | female | unknown
    health_status: Optional[str] = None
    vaccinated_status: Optional[str] = None   # vaccinated | not_vaccinated | unknown
    neutered_status: Optional[str] = None     # neutered | not_neutered | unknown
    adoption_reason: Optional[str] = None
    special_experience_required: bool = False


class AdoptionDetailsCreate(AdoptionDetailsBase):
    pass


class AdoptionDetailsRead(AdoptionDetailsBase):
    id: int
    item_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


# ── Service schemas ───────────────────────────────────────────────────────────

class ServiceDetailsBase(BaseModel):
    service_category: str
    pricing_model: PricingModel = PricingModel.negotiable
    service_mode: Optional[ServiceMode] = None
    service_area: Optional[str] = None
    availability_notes: Optional[str] = None
    experience_years: Optional[int] = None


class ServiceDetailsCreate(ServiceDetailsBase):
    @field_validator("service_category", mode="before")
    @classmethod
    def validate_service_category(cls, v) -> str:
        from app.domain.service_categories import assert_valid_service_category

        return assert_valid_service_category(str(v))


class ServiceDetailsRead(ServiceDetailsBase):
    id: int
    item_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


# ── Seller info (read-only snapshot shown on listing detail) ──────────────────

class SellerInfo(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    city: Optional[str] = None
    phone_number: Optional[str] = None   # only populated when allowed
    allow_messages: bool                 # whether this listing accepts messages

    model_config = {"from_attributes": True}


# ── Core Item schemas ─────────────────────────────────────────────────────────

class ItemBase(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    condition: Optional[ItemCondition] = None   # nullable — not required for services
    status: Optional[ItemStatus] = None
    is_public: bool = False
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Listing architecture
    listing_domain: ListingDomain = ListingDomain.item
    listing_type: Optional[ListingType] = None
    price: Optional[float] = None
    currency: str = "SAR"

    # Per-listing contact controls
    show_phone_in_listing: bool = False
    allow_messages: bool = True

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-90.0 <= v <= 90.0):
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-180.0 <= v <= 180.0):
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v


class ItemCreate(ItemBase):
    """Create payload; ``show_phone_in_listing=None`` uses ``app_settings.default_show_phone_in_listing``."""

    show_phone_in_listing: Optional[bool] = None
    tag_names: Optional[List[str]] = []
    adoption_details: Optional[AdoptionDetailsCreate] = None
    service_details: Optional[ServiceDetailsCreate] = None

    @model_validator(mode="after")
    def validate_listing_rules(self) -> "ItemCreate":
        _validate_listing_business_rules(
            listing_domain=self.listing_domain,
            listing_type=self.listing_type,
            price=self.price,
            adoption_details=self.adoption_details,
            service_details=self.service_details,
        )
        return self


class ItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    condition: Optional[ItemCondition] = None
    status: Optional[ItemStatus] = None
    is_public: Optional[bool] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    tag_names: Optional[List[str]] = None
    listing_domain: Optional[ListingDomain] = None
    listing_type: Optional[ListingType] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    show_phone_in_listing: Optional[bool] = None
    allow_messages: Optional[bool] = None
    adoption_details: Optional[AdoptionDetailsCreate] = None
    service_details: Optional[ServiceDetailsCreate] = None


class ItemRead(ItemBase):
    id: int
    user_id: int
    # Canonical service taxonomy key when listing_domain is service (mirrors service_details.service_category).
    service_category: Optional[str] = None
    images: List[ItemImageRead] = []
    tags: List[TagRead] = []
    ai_analysis: Optional[AIAnalysisRead] = None
    adoption_details: Optional[AdoptionDetailsRead] = None
    service_details: Optional[ServiceDetailsRead] = None
    seller: Optional[SellerInfo] = None
    is_favorited: Optional[bool] = None   # populated for authenticated API calls
    view_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Service listings only — provider-level aggregates, not listing-level
    provider_rating_summary: Optional[ProviderRatingSummary] = None
    viewer_provider_rating: Optional[ViewerProviderRating] = None
    listing_lifecycle: Optional[CanonicalListingLifecycle] = Field(
        default=None,
        description="Canonical lifecycle: draft | published | hidden | archived | deleted (derived from status + is_public).",
    )

    model_config = {"from_attributes": True}


class ItemSummary(BaseModel):
    id: int
    title: str
    listing_domain: ListingDomain = ListingDomain.item
    listing_type: Optional[ListingType] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    condition: Optional[ItemCondition] = None
    status: ItemStatus
    is_public: bool
    price: Optional[float] = None
    currency: str = "SAR"
    images: List[ItemImageRead] = []
    tags: List[TagRead] = []
    distance_km: Optional[float] = None
    ranking_score: Optional[float] = None
    ranking_reason: Optional[str] = None
    is_favorited: Optional[bool] = None
    created_at: datetime
    service_details: Optional[ServiceDetailsRead] = None
    listing_lifecycle: Optional[CanonicalListingLifecycle] = Field(
        default=None,
        description="Canonical lifecycle: draft | published | hidden | archived | deleted (derived from status + is_public).",
    )

    model_config = {"from_attributes": True}


# ── Search / filter params ────────────────────────────────────────────────────

class SearchParams(BaseModel):
    latitude: float
    longitude: float
    radius_km: float = 10.0
    category: Optional[str] = None
    query: Optional[str] = None
    listing_domain: Optional[ListingDomain] = None
    listing_type: Optional[ListingType] = None
    service_category: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v

    @field_validator("radius_km")
    @classmethod
    def validate_radius(cls, v: float) -> float:
        if not (0.1 <= v <= 100.0):
            raise ValueError("Search radius must be between 0.1 and 100 km")
        return v


# ── Similarity schemas (unchanged) ────────────────────────────────────────────

class RankingBreakdown(BaseModel):
    distance_score: float
    category_score: float
    keyword_score: float
    completeness_score: float
    ai_confidence_score: float
    fallback_penalty: float
    total_score: float
    # Phase 2 text vector / hybrid (optional; omitted in pure lexical search)
    text_vector_cosine: Optional[float] = None
    text_lexical_norm: Optional[float] = None
    text_hybrid_score: Optional[float] = None
    text_semantic_rank_score: Optional[float] = None
    text_search_mode_applied: Optional[str] = None
    text_search_fallback_reason: Optional[str] = None
    model_config = {"from_attributes": True}


class ItemSummaryWithBreakdown(BaseModel):
    id: int
    title: str
    listing_domain: ListingDomain = ListingDomain.item
    listing_type: Optional[ListingType] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    condition: Optional[ItemCondition] = None
    status: ItemStatus
    is_public: bool
    price: Optional[float] = None
    currency: str = "SAR"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    images: List[ItemImageRead] = []
    tags: List[TagRead] = []
    distance_km: Optional[float] = None
    ranking_score: Optional[float] = None
    ranking_reason: Optional[str] = None
    ranking_breakdown: Optional[RankingBreakdown] = None
    created_at: datetime
    service_details: Optional[ServiceDetailsRead] = None
    owner_city: Optional[str] = None
    listing_lifecycle: Optional[CanonicalListingLifecycle] = Field(
        default=None,
        description="Canonical lifecycle: draft | published | hidden | archived | deleted (derived from status + is_public).",
    )
    model_config = {"from_attributes": True}


class SimilarityRankingBreakdown(BaseModel):
    similarity_score: float
    distance_score: float
    category_score: float
    keyword_score: float
    completeness_score: float
    ai_confidence_score: float
    fallback_penalty: float
    total_score: float


class SimilarityBreakdown(BaseModel):
    similarity_score: float
    similarity_contribution: float
    distance_influence: float
    other_ranking: float
    final_score: float


class SimilarItemResult(BaseModel):
    id: int
    title: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    condition: Optional[ItemCondition] = None
    status: ItemStatus
    is_public: bool
    listing_lifecycle: Optional[CanonicalListingLifecycle] = Field(
        default=None,
        description="Canonical lifecycle: draft | published | hidden | archived | deleted (derived from status + is_public).",
    )
    images: List[ItemImageRead] = []
    tags: List[TagRead] = []
    similarity_score: float
    distance_km: Optional[float] = None
    ranking_score: float
    final_score: float
    ranking_breakdown: Optional[SimilarityRankingBreakdown] = None
    similarity_breakdown: Optional[SimilarityBreakdown] = None
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Business rule validation helper ──────────────────────────────────────────

def _validate_listing_business_rules(
    listing_domain: ListingDomain,
    listing_type: Optional[ListingType],
    price: Optional[float],
    adoption_details=None,
    service_details=None,
) -> None:
    """Central enforcement of listing domain/type business rules."""
    if listing_domain == ListingDomain.item:
        if listing_type is None:
            raise ValueError("listing_type is required for item listings (sale|donation|adoption)")
        if listing_type == ListingType.sale:
            if price is None or price <= 0:
                raise ValueError("Price is required and must be > 0 for sale listings")
        elif listing_type in (ListingType.donation, ListingType.adoption):
            if price is not None:
                raise ValueError(
                    f"Price must be null for {listing_type.value} listings"
                )
        if listing_type == ListingType.adoption and adoption_details is None:
            raise ValueError("adoption_details are required for adoption listings")
        if adoption_details is not None and listing_type != ListingType.adoption:
            raise ValueError("adoption_details can only be set on adoption listings")
        if service_details is not None:
            raise ValueError("service_details cannot be set on item listings")

    elif listing_domain == ListingDomain.service:
        if listing_type is not None:
            raise ValueError("listing_type must be null for service listings")
        if service_details is None:
            raise ValueError("service_details are required for service listings")
        if adoption_details is not None:
            raise ValueError("adoption_details cannot be set on service listings")
        # price is optional for services depending on pricing_model
        if service_details and service_details.pricing_model in (
            PricingModel.hourly, PricingModel.fixed
        ):
            if price is not None and price < 0:
                raise ValueError("Price must be >= 0 for service listings")
