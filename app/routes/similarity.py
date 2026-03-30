"""
Similarity search routes — find visually similar items.

Endpoints:
  GET  /api/similar/{item_id}   — find items similar to a given item
  POST /api/similar/by-image    — find items similar to an uploaded image
"""

import logging
import math
import uuid
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.item import SimilarItemResult, SimilarityBreakdown, SimilarityRankingBreakdown
from app.services import embedding_service
from app.services.listing_media_storage import temp_upload_dir
from app.domain.listing_lifecycle import canonical_listing_lifecycle

def _require_similarity_enabled():
    if not get_settings().enable_similarity_search:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Visual similarity search is temporarily unavailable.",
        )


router = APIRouter(
    prefix="/api/similar",
    tags=["similarity"],
    dependencies=[Depends(_require_similarity_enabled)],
)
settings = get_settings()
log = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _build_response(results: list) -> list[SimilarItemResult]:
    out: list[SimilarItemResult] = []
    for r in results:
        item = r["item"]
        st = str(getattr(item, "status", "available"))
        out.append(SimilarItemResult(
            id=item.id,
            title=item.title,
            category=item.category,
            subcategory=getattr(item, "subcategory", None),
            condition=item.condition,
            status=st,
            is_public=item.is_public,
            listing_lifecycle=canonical_listing_lifecycle(st, bool(item.is_public)),
            images=item.images,
            tags=item.tags,
            similarity_score=r["similarity_score"],
            distance_km=r["distance_km"],
            ranking_score=r["ranking_score"],
            final_score=r["final_score"],
            ranking_breakdown=SimilarityRankingBreakdown(**r["ranking_breakdown"]),
            similarity_breakdown=SimilarityBreakdown(**r["similarity_breakdown"]),
            created_at=item.created_at,
        ))
    return out


@router.get(
    "/{item_id}",
    response_model=PaginatedResponse[SimilarItemResult],
    summary="Find similar by item ID",
    response_description="Paginated list of public items ranked by visual similarity",
)
def similar_by_item(
    item_id: int,
    latitude: Optional[float] = Query(default=None, ge=-90.0, le=90.0),
    longitude: Optional[float] = Query(default=None, ge=-180.0, le=180.0),
    radius_km: Optional[float] = Query(default=None, ge=0.1, le=100.0),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
):
    """
    Find public items visually similar to the given item.

    Uses the item's stored image embedding (from OpenCLIP). Excludes the source item.
    Optional: filter by geographic radius (requires latitude + longitude).
    """
    if radius_km is not None and (latitude is None or longitude is None):
        raise HTTPException(
            status_code=400,
            detail="radius_km requires both latitude and longitude",
        )
    query_vector = embedding_service.get_embedding(db, item_id)
    if query_vector is None:
        raise HTTPException(
            status_code=404,
            detail="Item not found or has no embedding. Ensure the item has an analysed image.",
        )

    results, total_count = embedding_service.find_similar_items(
        db,
        query_vector,
        exclude_item_id=item_id,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        page=page,
        page_size=page_size,
    )
    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
    return PaginatedResponse(
        items=_build_response(results),
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
    )


@router.post(
    "/by-image",
    response_model=PaginatedResponse[SimilarItemResult],
    summary="Find similar by uploaded image",
    response_description="Paginated list of public items ranked by visual similarity",
)
async def similar_by_image(
    file: UploadFile = File(..., description="Image file (JPEG, PNG, WebP, GIF)"),
    latitude: Optional[float] = Query(default=None, ge=-90.0, le=90.0),
    longitude: Optional[float] = Query(default=None, ge=-180.0, le=180.0),
    radius_km: Optional[float] = Query(default=None, ge=0.1, le=100.0),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
):
    """
    Upload an image and find visually similar public items.

    Extracts an OpenCLIP embedding from the uploaded image and compares against
    all public items with embeddings. Optional: filter by geographic radius.
    """
    if radius_km is not None and (latitude is None or longitude is None):
        raise HTTPException(
            status_code=400,
            detail="radius_km requires both latitude and longitude",
        )
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    temp_dir = temp_upload_dir()

    ext = Path(file.filename or "upload").suffix or ".jpg"
    temp_path = temp_dir / f"sim_{uuid.uuid4().hex}{ext}"

    try:
        content = await file.read()
        if len(content) > settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large")
        temp_path.write_bytes(content)

        t0 = time.perf_counter()
        query_vector = await embedding_service.generate_embedding(
            temp_path, device=settings.ai_device,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        log.info("embedding_extraction duration_ms=%s", duration_ms)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    results, total_count = embedding_service.find_similar_items(
        db,
        query_vector,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        page=page,
        page_size=page_size,
    )
    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
    return PaginatedResponse(
        items=_build_response(results),
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
    )
