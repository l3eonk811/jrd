"""
AI — tagging / light classification from user-written text only.

No image enrichment, no generated titles or descriptions. See ``/api/ai/suggest-tags``.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List

from app.ai.text_to_tags import suggest_tags_from_text, get_minimum_content_length
from app.config import get_settings

router = APIRouter(prefix="/api/ai", tags=["ai"])


class TagSuggestionRequest(BaseModel):
    """Request for tag suggestions based on text content."""
    title: Optional[str] = None
    description: Optional[str] = None
    listing_domain: str = Field(..., description="item | service")
    listing_type: Optional[str] = Field(None, description="sale | donation | adoption")
    selected_category: Optional[str] = None
    service_category: Optional[str] = None
    animal_type: Optional[str] = None
    max_tags: int = Field(default=5, ge=1, le=10)


class TagSuggestionResponse(BaseModel):
    """Response with suggested tags."""
    suggested_tags: List[str]
    min_content_length: int


@router.post("/suggest-tags", response_model=TagSuggestionResponse)
def suggest_tags(payload: TagSuggestionRequest):
    """
    Generate suggested tags from user-written content.
    
    This endpoint reads title, description, and listing context to suggest
    domain-appropriate tags. No image processing is performed.
    
    Frontend should:
    - Only call this after user has written at least min_content_length characters
    - Use debouncing (500-1000ms) to avoid excessive requests
    - Show suggestions in UI without auto-applying them
    - Let user accept/edit/reject suggested tags
    """
    if not get_settings().enable_ai_suggest_tags:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tag suggestions are temporarily unavailable.",
        )
    suggested = suggest_tags_from_text(
        title=payload.title,
        description=payload.description,
        listing_domain=payload.listing_domain,
        listing_type=payload.listing_type,
        selected_category=payload.selected_category,
        service_category=payload.service_category,
        animal_type=payload.animal_type,
        max_tags=payload.max_tags
    )
    
    return TagSuggestionResponse(
        suggested_tags=suggested,
        min_content_length=get_minimum_content_length()
    )
