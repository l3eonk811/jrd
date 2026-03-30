"""
Text-to-tags AI service: Generate suggested tags from user-written content.

Simple, lightweight service that reads title, description, and listing context
to suggest domain-appropriate tags. No image processing.
"""

import logging
from typing import List, Optional
from app.ai import domain_taxonomy as dt

log = logging.getLogger(__name__)


def suggest_tags_from_text(
    title: Optional[str],
    description: Optional[str],
    listing_domain: str,
    listing_type: Optional[str] = None,
    selected_category: Optional[str] = None,
    service_category: Optional[str] = None,
    animal_type: Optional[str] = None,
    max_tags: int = 5
) -> List[str]:
    """
    Generate suggested tags from user-written text.
    
    Args:
        title: User's listing title
        description: User's listing description
        listing_domain: "item" | "service"
        listing_type: "sale" | "donation" | "adoption"
        selected_category: Selected category if any
        service_category: Service category if domain=service
        animal_type: Animal type if listing_type=adoption
        max_tags: Maximum number of tags to suggest
        
    Returns:
        List of suggested tags (domain-appropriate)
    """
    # Get allowed tags for this domain
    allowed_tags = dt.get_allowed_tags(listing_domain, listing_type)
    
    # Combine all text content
    text_content = " ".join(filter(None, [
        title or "",
        description or "",
        selected_category or "",
        service_category or "",
        animal_type or ""
    ])).lower()
    
    # If no content, return empty
    if not text_content.strip():
        return []
    
    # Simple keyword matching: find tags that match words in the content
    suggested = []
    
    for tag in allowed_tags:
        # Convert tag to words (e.g., "house-trained" -> ["house", "trained"])
        tag_words = tag.replace("-", " ").split()
        
        # Check if any tag word appears in content
        if any(word in text_content for word in tag_words):
            suggested.append(tag)
            if len(suggested) >= max_tags:
                break
    
    # If we found matches, return them
    if suggested:
        return suggested
    
    # Otherwise, return default tags based on domain/type
    return _get_default_tags(listing_domain, listing_type, selected_category, max_tags)


def _get_default_tags(
    listing_domain: str,
    listing_type: Optional[str],
    selected_category: Optional[str],
    max_tags: int
) -> List[str]:
    """Return sensible default tags when no keyword matches found."""
    
    if listing_domain == "item":
        if listing_type == "adoption":
            return ["friendly", "house-trained", "good-with-kids"][:max_tags]
        elif listing_type == "donation":
            return ["good-condition", "clean", "working"][:max_tags]
        else:  # sale
            return ["good-condition", "clean"][:max_tags]
    
    elif listing_domain == "service":
        return ["professional", "experienced", "reliable"][:max_tags]
    
    return []


def validate_suggested_tags(
    tags: List[str],
    listing_domain: str,
    listing_type: Optional[str] = None
) -> List[str]:
    """
    Validate that suggested tags are allowed for this domain.
    Filters out any tags that violate domain constraints.
    """
    return dt.filter_tags(tags, listing_domain, listing_type)


def get_minimum_content_length() -> int:
    """
    Return minimum number of characters needed before triggering suggestions.
    Frontend should only call suggest-tags API after user has written this much.
    """
    return 10  # At least 10 characters of combined title+description
