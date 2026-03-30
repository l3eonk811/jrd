"""
Domain-aware taxonomy for context-constrained AI inference.

Prevents cross-domain nonsense:
- Adoption listings must not get item-style tags like "portable", "barely-used"
- Service listings must not get object-specific tags
- Item listings get full item taxonomy

Each domain gets its own label space for categories, tags, and constraints.
"""

from dataclasses import dataclass
from typing import List, Set, Optional
from enum import Enum


class ListingDomain(str, Enum):
    ITEM = "item"
    SERVICE = "service"


class ListingType(str, Enum):
    SALE = "sale"
    DONATION = "donation"
    ADOPTION = "adoption"


# ══════════════════════════════════════════════════════════════════════════════
# ITEM DOMAIN (sale / donation)
# ══════════════════════════════════════════════════════════════════════════════

ITEM_CATEGORIES = [
    "Electronics", "Furniture", "Clothing", "Books", "Sports & Outdoors",
    "Kitchen & Dining", "Tools & Hardware", "Toys & Games", "Home Decor",
    "Vehicles", "Appliances", "Baby & Kids", "Pet Supplies", "Other"
]

# Tags appropriate for physical items (sale/donation)
ITEM_TAGS = {
    "portable", "compact", "lightweight", "heavy", "bulky",
    "brand-new", "barely-used", "vintage", "collectible",
    "assembled", "disassembled", "parts-included",
    "working", "as-is", "needs-repair",
    "original-box", "manual-included", "warranty",
}

# ══════════════════════════════════════════════════════════════════════════════
# ADOPTION DOMAIN (animals)
# ══════════════════════════════════════════════════════════════════════════════

ADOPTION_CATEGORIES = [
    "Dog", "Cat", "Bird", "Fish", "Rabbit", "Hamster", "Guinea Pig",
    "Reptile", "Farm Animal", "Other Animal"
]

# Tags appropriate for animal adoption
ADOPTION_TAGS = {
    "friendly", "playful", "calm", "energetic", "shy", "affectionate",
    "house-trained", "crate-trained", "leash-trained",
    "good-with-kids", "good-with-dogs", "good-with-cats",
    "indoor", "outdoor", "indoor-outdoor",
    "vaccinated", "spayed-neutered", "microchipped",
    "special-needs", "senior", "young", "adult",
}

# ══════════════════════════════════════════════════════════════════════════════
# SERVICE DOMAIN (professional services)
# ══════════════════════════════════════════════════════════════════════════════

SERVICE_CATEGORIES = [
    "Teacher", "Tutor", "Plumber", "Carpenter", "Electrician",
    "AC Technician", "Cleaner", "Photographer", "Trainer",
    "Home Repair", "Moving & Delivery", "Pet Care", "Childcare",
    "Other Service"
]

# Tags appropriate for service listings
SERVICE_TAGS = {
    "experienced", "licensed", "insured", "certified",
    "fast", "reliable", "professional", "affordable",
    "available-weekends", "available-evenings", "emergency-available",
    "residential", "commercial", "industrial",
    "english-speaker", "arabic-speaker", "bilingual",
}


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT-AWARE TAG FILTERING
# ══════════════════════════════════════════════════════════════════════════════

def get_allowed_tags(
    listing_domain: str,
    listing_type: Optional[str] = None
) -> Set[str]:
    """Return the set of tags allowed for this listing context."""
    if listing_domain == ListingDomain.ITEM.value:
        if listing_type == ListingType.ADOPTION.value:
            return ADOPTION_TAGS
        else:  # sale or donation
            return ITEM_TAGS
    elif listing_domain == ListingDomain.SERVICE.value:
        return SERVICE_TAGS
    else:
        # Unknown domain → allow item tags as fallback
        return ITEM_TAGS


def get_allowed_categories(
    listing_domain: str,
    listing_type: Optional[str] = None
) -> List[str]:
    """Return the list of categories allowed for this listing context."""
    if listing_domain == ListingDomain.ITEM.value:
        if listing_type == ListingType.ADOPTION.value:
            return ADOPTION_CATEGORIES
        else:
            return ITEM_CATEGORIES
    elif listing_domain == ListingDomain.SERVICE.value:
        return SERVICE_CATEGORIES
    else:
        return ITEM_CATEGORIES


def filter_tags(
    tags: List[str],
    listing_domain: str,
    listing_type: Optional[str] = None
) -> List[str]:
    """Filter tags to only those allowed in this listing context."""
    allowed = get_allowed_tags(listing_domain, listing_type)
    return [t for t in tags if t.lower().replace(" ", "-") in allowed]


def should_suppress_condition(
    listing_domain: str,
    listing_type: Optional[str] = None
) -> bool:
    """Return True if 'condition' field should be suppressed for this context."""
    # Adoption and service listings don't use condition
    if listing_domain == ListingDomain.SERVICE.value:
        return True
    if listing_domain == ListingDomain.ITEM.value and listing_type == ListingType.ADOPTION.value:
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT-AWARE PROMPTS (for zero-shot CLIP classification)
# ══════════════════════════════════════════════════════════════════════════════

def get_zero_shot_prompts(
    listing_domain: str,
    listing_type: Optional[str] = None,
    selected_category: Optional[str] = None
) -> List[str]:
    """
    Return context-appropriate zero-shot prompts for CLIP classification.
    If a category is already selected, return more specific prompts.
    """
    if listing_domain == ListingDomain.SERVICE.value:
        if selected_category:
            # Service with known category → very specific prompts
            cat_lower = selected_category.lower()
            if "teach" in cat_lower or "tutor" in cat_lower:
                return [
                    "a photo of a teacher or tutor in a classroom",
                    "a photo of educational materials and books",
                    "a photo of a person teaching or tutoring",
                ]
            elif "plumb" in cat_lower:
                return [
                    "a photo of plumbing tools and pipes",
                    "a photo of a plumber at work",
                    "a photo of bathroom or kitchen plumbing",
                ]
            else:
                return [f"a photo related to {selected_category} service"]
        else:
            # Service with no category → generic service prompts
            return [
                "a photo of a professional service provider at work",
                "a photo of tools or equipment for a service",
                "a photo of a person providing a service",
            ]
    
    elif listing_domain == ListingDomain.ITEM.value and listing_type == ListingType.ADOPTION.value:
        if selected_category:
            cat_lower = selected_category.lower()
            return [
                f"a photo of a {cat_lower}",
                f"a close-up photo of a {cat_lower}",
                f"a {cat_lower} looking at the camera",
            ]
        else:
            return [
                "a photo of a pet animal",
                "a photo of a dog or cat",
                "a photo of an animal looking at the camera",
            ]
    
    else:
        # Item (sale/donation) → object-focused prompts
        if selected_category:
            cat_lower = selected_category.lower()
            return [
                f"a photo of {cat_lower}",
                f"a {cat_lower} product photo",
                f"a {cat_lower} on a white background",
            ]
        else:
            return [
                "a photo of a household item or product",
                "a product photo on a clean background",
                "a photo of an object for sale",
            ]


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline / tests: DomainConstraints (blocked vs allowed tags + category bounds)
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class DomainConstraints:
    """Constraint bundle used by the AI pipeline and unit tests."""

    blocked_tags: Set[str]
    allowed_tags: Optional[Set[str]]
    allowed_categories: Optional[List[str]]
    suppress_condition: bool


# Item-style tags that must not appear on adoption listings (subset of ITEM_TAGS minus ADOPTION_TAGS).
ADOPTION_BLOCKED_TAGS: Set[str] = set(ITEM_TAGS) - set(ADOPTION_TAGS)
ADOPTION_BLOCKED_TAGS.update({"electric", "kitchen"})

SERVICE_BLOCKED_TAGS: Set[str] = set(ITEM_TAGS) - set(SERVICE_TAGS)
SERVICE_BLOCKED_TAGS.update({"wooden"})


def _norm_tag_label(t: str) -> str:
    return t.lower().replace(" ", "-")


def get_constraints(
    listing_domain: Optional[str],
    listing_type: Optional[str] = None,
) -> DomainConstraints:
    d = (listing_domain or "").strip().lower() or None
    lt = (listing_type or "").strip().lower() if listing_type else None

    if d == ListingDomain.ITEM.value:
        if lt in (ListingType.SALE.value, ListingType.DONATION.value):
            return DomainConstraints(
                blocked_tags=set(),
                allowed_tags=None,
                allowed_categories=list(ITEM_CATEGORIES),
                suppress_condition=False,
            )
        if lt == ListingType.ADOPTION.value:
            return DomainConstraints(
                blocked_tags=set(ADOPTION_BLOCKED_TAGS),
                allowed_tags=set(ADOPTION_TAGS),
                allowed_categories=list(ADOPTION_CATEGORIES),
                suppress_condition=True,
            )
    if d == ListingDomain.SERVICE.value:
        return DomainConstraints(
            blocked_tags=set(SERVICE_BLOCKED_TAGS),
            allowed_tags=set(SERVICE_TAGS),
            allowed_categories=list(SERVICE_CATEGORIES),
            suppress_condition=True,
        )
    return DomainConstraints(
        blocked_tags=set(),
        allowed_tags=None,
        allowed_categories=None,
        suppress_condition=False,
    )


def filter_tags_by_constraints(
    tags: List[str],
    c: DomainConstraints,
    max_tags: int = 5,
) -> List[str]:
    """Drop tags that appear in ``blocked_tags`` (normalized), keep order, cap length."""
    blocked = {_norm_tag_label(b) for b in c.blocked_tags}
    out: List[str] = []
    for t in tags:
        if _norm_tag_label(t) in blocked:
            continue
        out.append(t)
        if len(out) >= max_tags:
            break
    return out


def constrain_category(category: str, c: DomainConstraints) -> str:
    """Map a suggested category into the allowed list for this domain, or ``Other``."""
    if not c.allowed_categories:
        return category
    cat = category.strip()
    for ac in c.allowed_categories:
        if ac.lower() == cat.lower():
            return cat
    if cat in ("Cats", "Dogs"):
        return cat
    return "Other"
