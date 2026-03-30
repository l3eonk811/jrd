import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.item import ItemSummaryWithBreakdown, RankingBreakdown
from app.services import item_service
from app.config import get_settings
from app.domain.listing_lifecycle import canonical_listing_lifecycle
from app.domain.service_categories import assert_valid_service_category

router = APIRouter(prefix="/api/search", tags=["search"])
_settings = get_settings()
_DEFAULT_BOUNDS_PAGE = min(100, _settings.search_bounds_max_page_size)


def _parse_service_category_filter(raw: Optional[str]) -> Optional[str]:
    """Validate optional ``service_category`` query param against the controlled vocabulary."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        return assert_valid_service_category(s)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid service_category; must be a known service taxonomy key.",
        )


def _lon_span_degrees(west: float, east: float) -> float:
    """Longitude span in degrees, accounting for antimeridian crossing."""
    if west <= east:
        return east - west
    return 360.0 - (west - east)


def _build_summary(r: dict) -> ItemSummaryWithBreakdown:
    item = r["item"]
    breakdown = RankingBreakdown(**r["ranking_breakdown"])
    st = str(getattr(item, "status", "available"))
    return ItemSummaryWithBreakdown(
        id=item.id,
        title=item.title,
        listing_domain=item.listing_domain,
        listing_type=item.listing_type,
        category=item.category,
        subcategory=item.subcategory,
        condition=item.condition,
        status=st,
        is_public=item.is_public,
        listing_lifecycle=canonical_listing_lifecycle(st, bool(item.is_public)),
        price=item.price,
        currency=item.currency,
        latitude=item.latitude,
        longitude=item.longitude,
        images=item.images,
        tags=item.tags,
        distance_km=r.get("distance_km"),
        ranking_score=r["ranking_score"],
        ranking_reason=r["ranking_reason"],
        ranking_breakdown=breakdown,
        created_at=item.created_at,
        service_details=item.service_details,
        owner_city=item.owner.city if item.owner else None,
    )


@router.get("", response_model=PaginatedResponse[ItemSummaryWithBreakdown])
def search_items(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    radius_km: float = Query(default=10.0, ge=0.1, le=100.0),
    category: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    listing_domain: Optional[str] = Query(default=None, description="item | service"),
    listing_type: Optional[str] = Query(default=None, description="sale | donation | adoption"),
    service_category: Optional[str] = Query(default=None),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    sort: Optional[str] = Query(
        default=None,
        description="newest | nearest | oldest | price_asc | price_desc. Omit for location-first (nearest).",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=_settings.search_max_page_size),
    text_search_mode: Optional[str] = Query(
        default=None,
        description="lexical (default) | hybrid | semantic — hybrid/semantic require non-empty query; see docs/TEXT_VECTOR_SEARCH.md",
    ),
    db: Session = Depends(get_db),
):
    sc = _parse_service_category_filter(service_category)
    results, total_count = item_service.search_nearby_items(
        db,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        category=category,
        query=query,
        listing_domain=listing_domain,
        listing_type=listing_type,
        service_category=sc,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        page=page,
        page_size=page_size,
        text_search_mode=text_search_mode,
    )
    summaries = [_build_summary(r) for r in results]
    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
    return PaginatedResponse(
        items=summaries,
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
    )


@router.get("/bounds", response_model=PaginatedResponse[ItemSummaryWithBreakdown])
def search_by_bounds(
    north: float = Query(..., ge=-90.0, le=90.0),
    south: float = Query(..., ge=-90.0, le=90.0),
    east: float = Query(..., ge=-180.0, le=180.0),
    west: float = Query(..., ge=-180.0, le=180.0),
    center_latitude: Optional[float] = Query(default=None, ge=-90.0, le=90.0),
    center_longitude: Optional[float] = Query(default=None, ge=-180.0, le=180.0),
    category: Optional[str] = Query(default=None),
    subcategory: Optional[str] = Query(default=None),
    condition: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    listing_domain: Optional[str] = Query(default=None),
    listing_type: Optional[str] = Query(default=None),
    service_category: Optional[str] = Query(default=None),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    sort: Optional[str] = Query(
        default=None,
        description="newest | nearest | oldest | price_asc | price_desc. Omit for location-first when center is set, else newest.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_BOUNDS_PAGE, ge=1, le=_settings.search_bounds_max_page_size),
    text_search_mode: Optional[str] = Query(
        default=None,
        description="lexical (default) | hybrid | semantic",
    ),
    db: Session = Depends(get_db),
):
    sc = _parse_service_category_filter(service_category)
    if south >= north:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="South latitude must be less than north latitude",
        )

    max_span = _settings.search_bounds_max_degrees_span
    if (north - south) > max_span or _lon_span_degrees(west, east) > max_span:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Map area is too large; zoom in to search this view.",
        )

    results, total_count = item_service.search_by_bounds(
        db,
        north=north,
        south=south,
        east=east,
        west=west,
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        category=category,
        subcategory=subcategory,
        condition=condition,
        query=query,
        listing_domain=listing_domain,
        listing_type=listing_type,
        service_category=sc,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        page=page,
        page_size=page_size,
        text_search_mode=text_search_mode,
    )
    summaries = [_build_summary(r) for r in results]
    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
    return PaginatedResponse(
        items=summaries,
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
    )
