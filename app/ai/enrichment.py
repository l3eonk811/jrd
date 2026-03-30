"""
Publish-time AI enrichment service.

Automatically assigns category, subcategory, and tags when a listing is published.
Uses only text content and structured fields - no image analysis.
"""

import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass

from app.ai import domain_taxonomy as dt
from app.domain.service_categories import SERVICE_CATEGORY_KEYS

log = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Result of AI enrichment at publish time."""
    category: str
    subcategory: Optional[str]
    tags: List[str]
    confidence: float  # 0.0 to 1.0
    method: str  # "keyword_match" | "default_fallback"


# Confidence thresholds
HIGH_CONFIDENCE = 0.7
MEDIUM_CONFIDENCE = 0.4
LOW_CONFIDENCE = 0.2


def enrich_listing(
    title: Optional[str],
    description: Optional[str],
    listing_domain: str,
    listing_type: Optional[str] = None,
    service_category: Optional[str] = None,
    animal_type: Optional[str] = None,
) -> EnrichmentResult:
    """
    Enrich a listing with category, subcategory, and tags at publish time.
    
    This runs ONLY when user publishes (not during draft writing).
    Uses controlled taxonomy - no free-form generation.
    
    Args:
        title: User's listing title
        description: User's listing description
        listing_domain: "item" | "service"
        listing_type: "sale" | "donation" | "adoption"
        service_category: Service category if domain=service
        animal_type: Animal type if listing_type=adoption
        
    Returns:
        EnrichmentResult with category, subcategory, tags, confidence
    """
    # Get allowed categories for this domain
    allowed_categories = dt.get_allowed_categories(listing_domain, listing_type)
    
    # Combine all text content for analysis
    text_content = " ".join(filter(None, [
        title or "",
        description or "",
        service_category or "",
        animal_type or ""
    ])).lower()
    
    # Infer category, subcategory, tags
    category, subcategory, confidence = _infer_category(
        text_content,
        allowed_categories,
        listing_domain,
        listing_type,
        service_category,
        animal_type
    )
    
    # Infer tags based on text + category
    tags = _infer_tags(
        text_content,
        category,
        listing_domain,
        listing_type,
        confidence
    )
    
    method = "keyword_match" if confidence >= MEDIUM_CONFIDENCE else "default_fallback"
    
    return EnrichmentResult(
        category=category,
        subcategory=subcategory,
        tags=tags,
        confidence=confidence,
        method=method
    )


def _infer_category(
    text: str,
    allowed_categories: List[str],
    listing_domain: str,
    listing_type: Optional[str],
    service_category: Optional[str],
    animal_type: Optional[str]
) -> Tuple[str, Optional[str], float]:
    """
    Infer category and subcategory from text content.
    
    Returns:
        (category, subcategory, confidence)
    """
    from app.ai.taxonomy import MAIN_CATEGORIES, MAIN_CATEGORY_IDS
    
    # If service_category or animal_type provided, use them directly
    if listing_domain == "service" and service_category:
        # Structured service taxonomy (English keys); distinct from display-oriented ``allowed_categories``.
        if service_category in SERVICE_CATEGORY_KEYS:
            return service_category, None, 0.9
    
    if listing_type == "adoption" and animal_type:
        # Animal type maps to category
        for cat in allowed_categories:
            if animal_type.lower() in cat.lower():
                return cat, None, 0.9
        # Fallback: use animal_type as category if it's in allowed list
        if animal_type in allowed_categories:
            return animal_type, None, 0.8
    
    # Keyword matching for categories
    matches = []
    for category in allowed_categories:
        category_lower = category.lower()
        category_words = category_lower.replace(" / ", " ").replace("/", " ").split()
        
        # Count how many category words appear in text
        match_count = sum(1 for word in category_words if word in text)
        if match_count > 0:
            # Calculate score: matches / total_words
            score = match_count / len(category_words)
            matches.append((category, score))
    
    # Sort by score descending
    matches.sort(key=lambda x: x[1], reverse=True)
    
    if matches and matches[0][1] >= 0.5:
        # Strong match found
        category = matches[0][0]
        confidence = min(matches[0][1], 0.85)
        
        # Try to infer subcategory if we have a strong category match
        subcategory = _infer_subcategory(text, category, confidence)
        
        return category, subcategory, confidence
    
    # Weak or no matches - use default fallback
    category = _get_default_category(listing_domain, listing_type)
    confidence = LOW_CONFIDENCE
    
    return category, None, confidence


def _infer_subcategory(text: str, category: str, category_confidence: float) -> Optional[str]:
    """
    Infer subcategory from text given a category.
    Only attempts if category confidence is reasonable.
    Returns None if no good subcategory match found.
    """
    if category_confidence < MEDIUM_CONFIDENCE:
        return None  # Category too uncertain for subcategory
    
    from app.ai.taxonomy import MAIN_CATEGORIES
    
    # Find the main category definition
    main_cat = None
    for cat in MAIN_CATEGORIES:
        if cat.label_en == category:
            main_cat = cat
            break
    
    if not main_cat or not main_cat.subcategories:
        return None  # No subcategories defined for this category
    
    # Keyword matching for subcategories
    matches = []
    for subcat in main_cat.subcategories:
        subcat_lower = subcat.label_en.lower()
        subcat_words = subcat_lower.replace(" & ", " ").replace("/", " ").split()
        
        # Count matches
        match_count = sum(1 for word in subcat_words if word in text)
        if match_count > 0:
            score = match_count / len(subcat_words)
            matches.append((subcat.label_en, score))
    
    # Sort by score descending
    matches.sort(key=lambda x: x[1], reverse=True)
    
    # Only return subcategory if we have strong confidence (>= 0.6)
    if matches and matches[0][1] >= 0.6:
        return matches[0][0]
    
    return None  # No strong subcategory match


def _infer_tags(
    text: str,
    category: str,
    listing_domain: str,
    listing_type: Optional[str],
    confidence: float
) -> List[str]:
    """
    Infer tags from text content.
    Returns controlled vocabulary tags only.
    """
    if not text or len(text) < 5:
        # Very short text - return minimal safe tags
        return _get_minimal_tags(listing_domain, listing_type, confidence)
    
    # Get allowed tags for this domain
    allowed_tags = dt.get_allowed_tags(listing_domain, listing_type)
    
    # Keyword matching
    matched_tags = []
    for tag in allowed_tags:
        tag_words = tag.replace("-", " ").split()
        
        # Check if any tag word appears in text
        if any(word in text for word in tag_words):
            matched_tags.append(tag)
            if len(matched_tags) >= 5:  # Max 5 tags
                break
    
    if matched_tags:
        return matched_tags
    
    # No matches - return safe defaults
    return _get_minimal_tags(listing_domain, listing_type, confidence)


def _get_default_category(
    listing_domain: str,
    listing_type: Optional[str]
) -> str:
    """Return safe default category when confidence is low."""
    if listing_domain == "item":
        if listing_type == "adoption":
            return "Other Animal"
        else:
            return "Other"
    elif listing_domain == "service":
        return "Other Service"
    else:
        return "Other"


def _get_minimal_tags(
    listing_domain: str,
    listing_type: Optional[str],
    confidence: float
) -> List[str]:
    """
    Return minimal safe tags based on domain.
    Only return tags when confidence is reasonable.
    """
    if confidence < LOW_CONFIDENCE:
        return []  # Too uncertain - no tags
    
    if listing_domain == "item":
        if listing_type == "adoption":
            return ["friendly"]
        elif listing_type == "donation":
            return ["good-condition"]
        else:  # sale
            return []  # Let price speak for itself
    
    elif listing_domain == "service":
        return ["professional"]
    
    return []


def can_user_edit_category() -> bool:
    """
    Return True if users can edit category after publish.
    Currently: No, category is AI-assigned only.
    """
    return False


def can_user_edit_tags() -> bool:
    """
    Return True if users can edit tags.
    Currently: No, tags are AI-assigned only.
    """
    return False
