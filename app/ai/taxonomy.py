"""
Normalized taxonomy for the OpenCLIP pipeline (MVP).

Structured groups:
- Main categories (with optional subcategories; each sub belongs to one main)
- Condition labels (canonical: new, like_new, good, fair, poor)
- Material / usage / decision tags (approved set only; no free-form)
- Per-category allowed tags (reduces irrelevant tag predictions)

Helpers: get_main_category_prompts, get_subcategory_prompts,
get_allowed_tags_for_category, normalize_* (category, condition, tag),
filter_allowed_tags, build_title.

Extensible for i18n: add label_ar (or labels: Dict[str, str]) to
MainCategoryDef / SubCategoryDef and use in prompts per locale.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, FrozenSet

# ── Condition labels (canonical values match ItemCondition) ───────────────────

@dataclass(frozen=True)
class ConditionDef:
    value: str
    label: str
    description: str


CONDITIONS: Tuple[ConditionDef, ...] = (
    ConditionDef("new", "New", "Unused, original packaging"),
    ConditionDef("like_new", "Like New", "Used once or twice, no visible wear"),
    ConditionDef("good", "Good", "Normal use, minor cosmetic marks only"),
    ConditionDef("fair", "Fair", "Noticeable wear, fully functional"),
    ConditionDef("poor", "Poor", "Heavy wear or minor defects, still usable"),
)

CONDITION_VALUES: Tuple[str, ...] = tuple(c.value for c in CONDITIONS)
_CONDITION_BY_VALUE: Dict[str, str] = {c.value: c.value for c in CONDITIONS}
_CONDITION_LOWER: Dict[str, str] = {c.value.lower(): c.value for c in CONDITIONS}


# ── Approved tag groups (normalized, restricted set) ─────────────────────────

MATERIAL_TAGS: Tuple[str, ...] = (
    "wooden", "metal", "plastic", "fabric", "glass", "leather",
    "bamboo", "ceramic", "stainless-steel", "paper", "cardboard",
)

USAGE_TAGS: Tuple[str, ...] = (
    "portable", "outdoor", "indoor", "decorative", "storage",
    "compact", "wall-mount", "handheld", "electric", "manual",
    "kitchen", "office", "garden", "sports", "kids", "wireless",
)

DECISION_TAGS: Tuple[str, ...] = (
    "vintage", "bundle", "gift-worthy", "quick-pickup",
    "needs-cleaning", "pet-free-home", "smoke-free-home",
    "complete-set", "barely-used", "handmade", "eco-friendly",
    "misc",
)

# Single approved set for normalization and validation.
APPROVED_TAGS: FrozenSet[str] = frozenset(
    MATERIAL_TAGS + USAGE_TAGS + DECISION_TAGS
)


# ── Subcategory (belongs to exactly one main category) ────────────────────────

@dataclass(frozen=True)
class SubCategoryDef:
    id: str
    label_en: str


# ── Main category ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MainCategoryDef:
    id: str
    label_en: str
    subcategories: Tuple[SubCategoryDef, ...] = ()
    allowed_tag_ids: Tuple[str, ...] = ()  # subset of APPROVED_TAGS
    title_templates: Tuple[str, ...] = ()  # for title generation fallback


# MVP: Expanded set of main categories with better coverage for household and common items.

MAIN_CATEGORIES: Tuple[MainCategoryDef, ...] = (
    MainCategoryDef(
        id="vehicles",
        label_en="Vehicles",
        subcategories=(
            SubCategoryDef("cars", "Cars"),
            SubCategoryDef("motorcycles", "Motorcycles"),
            SubCategoryDef("bicycles", "Bicycles"),
            SubCategoryDef("parts", "Parts & Accessories"),
        ),
        allowed_tag_ids=("metal", "portable", "outdoor", "compact", "vintage", "barely-used"),
        title_templates=("Car", "Motorcycle", "Bicycle", "Car Parts", "Bike Accessories"),
    ),
    MainCategoryDef(
        id="electronics",
        label_en="Electronics",
        subcategories=(
            SubCategoryDef("audio", "Audio"),
            SubCategoryDef("computing", "Computing"),
            SubCategoryDef("gaming", "Gaming"),
            SubCategoryDef("phone_tablet", "Phone & Tablet"),
            SubCategoryDef("elec_lighting", "Lighting"),
            SubCategoryDef("cameras", "Cameras"),
        ),
        allowed_tag_ids=("portable", "metal", "plastic", "electric", "compact", "wireless", "barely-used", "complete-set"),
        title_templates=("Bluetooth Speaker", "LED Desk Lamp", "USB Hub", "Gaming Controller", "Tablet", "Digital Camera"),
    ),
    MainCategoryDef(
        id="furniture",
        label_en="Furniture",
        subcategories=(
            SubCategoryDef("seating", "Seating"),
            SubCategoryDef("tables", "Tables"),
            SubCategoryDef("storage", "Storage"),
            SubCategoryDef("furn_lighting", "Lighting"),
            SubCategoryDef("beds", "Beds & Mattresses"),
        ),
        allowed_tag_ids=("wooden", "metal", "fabric", "storage", "indoor", "decorative", "compact", "vintage"),
        title_templates=("Wooden Bookshelf", "Office Chair", "Coffee Table", "Floor Lamp", "Shoe Rack", "Bed Frame"),
    ),
    MainCategoryDef(
        id="appliances",
        label_en="Appliances",
        subcategories=(
            SubCategoryDef("kitchen_appliances", "Kitchen"),
            SubCategoryDef("laundry", "Laundry"),
            SubCategoryDef("heating_cooling", "Heating & Cooling"),
            SubCategoryDef("cleaning", "Cleaning"),
        ),
        allowed_tag_ids=("electric", "metal", "plastic", "compact", "kitchen", "indoor", "barely-used"),
        title_templates=("Microwave", "Washing Machine", "Space Heater", "Vacuum Cleaner", "Coffee Maker"),
    ),
    MainCategoryDef(
        id="clothing",
        label_en="Clothing",
        subcategories=(
            SubCategoryDef("outerwear", "Outerwear"),
            SubCategoryDef("footwear", "Footwear"),
            SubCategoryDef("accessories", "Accessories"),
            SubCategoryDef("bags", "Bags"),
        ),
        allowed_tag_ids=("fabric", "leather", "portable", "outdoor", "compact", "vintage", "barely-used"),
        title_templates=("Winter Jacket", "Running Shoes", "Backpack", "Leather Belt", "Wool Scarf"),
    ),
    MainCategoryDef(
        id="books",
        label_en="Books",
        subcategories=(
            SubCategoryDef("fiction", "Fiction"),
            SubCategoryDef("nonfiction", "Nonfiction"),
            SubCategoryDef("children", "Children"),
            SubCategoryDef("reference", "Reference"),
        ),
        allowed_tag_ids=("paper", "indoor", "vintage", "complete-set", "gift-worthy"),
        title_templates=("Novel", "Cookbook", "Textbook", "Picture Book", "Box Set"),
    ),
    MainCategoryDef(
        id="sports_outdoors",
        label_en="Sports & Outdoors",
        subcategories=(
            SubCategoryDef("fitness", "Fitness"),
            SubCategoryDef("camping", "Camping"),
            SubCategoryDef("cycling", "Cycling"),
            SubCategoryDef("water", "Water Sports"),
        ),
        allowed_tag_ids=("portable", "outdoor", "compact", "metal", "fabric", "eco-friendly", "barely-used"),
        title_templates=("Yoga Mat", "Dumbbell Set", "Camping Tent", "Bicycle Helmet", "Sleeping Bag"),
    ),
    MainCategoryDef(
        id="kitchen",
        label_en="Kitchen",
        subcategories=(
            SubCategoryDef("small_appliances", "Small Appliances"),
            SubCategoryDef("cookware", "Cookware"),
            SubCategoryDef("utensils", "Utensils"),
            SubCategoryDef("storage_containers", "Storage & Containers"),
        ),
        allowed_tag_ids=("metal", "plastic", "glass", "stainless-steel", "compact", "kitchen", "complete-set", "barely-used"),
        title_templates=("Stand Mixer", "Cast Iron Skillet", "Blender", "Knife Set", "Food Storage"),
    ),
    MainCategoryDef(
        id="tools",
        label_en="Tools",
        subcategories=(
            SubCategoryDef("power", "Power Tools"),
            SubCategoryDef("hand", "Hand Tools"),
            SubCategoryDef("measuring", "Measuring"),
            SubCategoryDef("gardening", "Gardening"),
        ),
        allowed_tag_ids=("metal", "plastic", "electric", "manual", "compact", "complete-set", "barely-used", "outdoor"),
        title_templates=("Cordless Drill", "Wrench Set", "Laser Level", "Toolbox", "Hand Saw", "Garden Hose"),
    ),
    MainCategoryDef(
        id="toys_games",
        label_en="Toys & Games",
        subcategories=(
            SubCategoryDef("board_games", "Board Games"),
            SubCategoryDef("building", "Building"),
            SubCategoryDef("outdoor_play", "Outdoor Play"),
            SubCategoryDef("educational", "Educational"),
        ),
        allowed_tag_ids=("plastic", "wooden", "kids", "indoor", "outdoor", "complete-set", "vintage", "gift-worthy"),
        title_templates=("Board Game", "LEGO Set", "Puzzle", "Card Game", "Chess Set"),
    ),
    MainCategoryDef(
        id="home_decor",
        label_en="Home & Decor",
        subcategories=(
            SubCategoryDef("art", "Art & Prints"),
            SubCategoryDef("decor", "Decor"),
            SubCategoryDef("collectibles", "Collectibles"),
            SubCategoryDef("plants", "Plants"),
        ),
        allowed_tag_ids=("decorative", "indoor", "wall-mount", "vintage", "handmade", "glass", "ceramic", "gift-worthy"),
        title_templates=("Framed Print", "Vase", "Mirror", "Sculpture", "Wall Art", "Potted Plant"),
    ),
    MainCategoryDef(
        id="baby_kids",
        label_en="Baby & Kids",
        subcategories=(
            SubCategoryDef("baby_gear", "Baby Gear"),
            SubCategoryDef("kids_furniture", "Kids Furniture"),
            SubCategoryDef("baby_clothes", "Baby Clothes"),
        ),
        allowed_tag_ids=("plastic", "fabric", "kids", "indoor", "portable", "compact", "barely-used", "complete-set"),
        title_templates=("Baby Stroller", "High Chair", "Baby Clothes", "Crib", "Diaper Bag"),
    ),
    MainCategoryDef(
        id="pet_supplies",
        label_en="Pet Supplies",
        subcategories=(
            SubCategoryDef("pet_accessories", "Accessories"),
            SubCategoryDef("pet_toys", "Toys"),
            SubCategoryDef("pet_furniture", "Furniture"),
        ),
        allowed_tag_ids=("plastic", "fabric", "portable", "indoor", "outdoor", "compact", "barely-used"),
        title_templates=("Dog Bed", "Cat Tree", "Pet Carrier", "Dog Leash", "Pet Bowl"),
    ),
    MainCategoryDef(
        id="other",
        label_en="Other",
        subcategories=(),
        allowed_tag_ids=("bundle", "quick-pickup", "needs-cleaning", "misc"),
        title_templates=("Household Item", "Assorted Lot", "Storage Box", "Misc Item"),
    ),
)

# Canonical ordering and lookups.
MAIN_CATEGORY_IDS: Tuple[str, ...] = tuple(m.id for m in MAIN_CATEGORIES)
_MAIN_BY_ID: Dict[str, MainCategoryDef] = {m.id: m for m in MAIN_CATEGORIES}
_MAIN_BY_LABEL_LOWER: Dict[str, MainCategoryDef] = {m.label_en.lower(): m for m in MAIN_CATEGORIES}


# ── Backward compatibility for mock classifier ────────────────────────────────

@dataclass(frozen=True)
class CategoryDef:
    titles: Tuple[str, ...]
    tags: Tuple[str, ...]
    keywords: Tuple[str, ...]


# Build legacy CATEGORIES dict and CATEGORY_NAMES from main categories.
CATEGORIES: Dict[str, CategoryDef] = {
    m.label_en: CategoryDef(
        titles=m.title_templates,
        tags=m.allowed_tag_ids,
        keywords=(f"a photo of {m.label_en.lower()}",),
    )
    for m in MAIN_CATEGORIES
}
CATEGORY_NAMES: List[str] = [m.label_en for m in MAIN_CATEGORIES]
GLOBAL_TAGS: List[str] = list(APPROVED_TAGS)


# ── Helper: category prompts ──────────────────────────────────────────────────

def get_main_category_prompts() -> List[Tuple[str, str, str]]:
    """Return (main_id, label_en, prompt) for each main category."""
    # Rich prompts with descriptive context for better classification
    category_prompts_map = {
        "vehicles": "a photo of a vehicle, car, motorcycle, bicycle, or vehicle part",
        "electronics": "a photo of electronic devices like phones, computers, speakers, cameras, or gaming consoles",
        "furniture": "a photo of furniture such as chairs, tables, sofas, shelves, beds, or cabinets",
        "appliances": "a photo of home appliances like refrigerator, microwave, washing machine, vacuum cleaner, or oven",
        "clothing": "a photo of clothing, shoes, bags, or fashion accessories",
        "books": "a photo of books, magazines, textbooks, or reading materials",
        "sports_outdoors": "a photo of sports equipment, fitness gear, camping gear, or outdoor recreation items",
        "kitchen": "a photo of kitchen items like cookware, utensils, dishes, pots, pans, or food containers",
        "tools": "a photo of tools, hand tools, power tools, toolbox, or hardware equipment",
        "toys_games": "a photo of toys, games, puzzles, board games, or children's playthings",
        "home_decor": "a photo of home decoration like artwork, vases, mirrors, plants, or decorative objects",
        "baby_kids": "a photo of baby gear, kids furniture, strollers, cribs, or children's items",
        "pet_supplies": "a photo of pet supplies, pet bed, pet toys, or animal accessories",
        "other": "a photo of miscellaneous household items or objects",
    }
    
    return [
        (m.id, m.label_en, category_prompts_map.get(m.id, f"a photo of {m.label_en}"))
        for m in MAIN_CATEGORIES
    ]


def get_subcategory_prompts(main_id: str) -> List[Tuple[str, str, str]]:
    """Return (sub_id, label_en, prompt) for each subcategory of main_id."""
    main = _MAIN_BY_ID.get(main_id)
    if not main or not main.subcategories:
        return []
    
    # Special subcategory prompts for better classification
    subcategory_prompts_map = {
        # Vehicles
        "cars": "a photo of a car, automobile, sedan, SUV, or passenger vehicle",
        "motorcycles": "a photo of a motorcycle, motorbike, or scooter",
        "bicycles": "a photo of a bicycle, bike, or cycling equipment",
        "parts": "a photo of vehicle parts, car parts, tires, or automotive accessories",
        
        # Electronics
        "audio": "a photo of audio equipment like speakers, headphones, or sound systems",
        "computing": "a photo of computers, laptops, monitors, keyboards, or computer accessories",
        "gaming": "a photo of gaming consoles, controllers, or gaming equipment",
        "phone_tablet": "a photo of phones, smartphones, tablets, or mobile devices",
        "cameras": "a photo of cameras, DSLR, digital cameras, or photography equipment",
        
        # Kitchen
        "small_appliances": "a photo of small kitchen appliances like toaster, coffee maker, or blender",
        "cookware": "a photo of cookware like pots, pans, or cooking vessels",
        "storage_containers": "a photo of food storage containers, Tupperware, or kitchen storage",
        
        # Appliances
        "kitchen_appliances": "a photo of major kitchen appliances like refrigerator, oven, or dishwasher",
        "laundry": "a photo of laundry appliances like washing machine or dryer",
        "heating_cooling": "a photo of heating or cooling equipment like heater, air conditioner, or fan",
        "cleaning": "a photo of cleaning appliances like vacuum cleaner or steam cleaner",
        
        # Tools
        "gardening": "a photo of gardening tools, garden equipment, or yard maintenance tools",
        
        # Baby & Kids
        "baby_gear": "a photo of baby gear like strollers, car seats, or baby carriers",
        "kids_furniture": "a photo of children's furniture like cribs, changing tables, or kids chairs",
        
        # Pet Supplies
        "pet_accessories": "a photo of pet accessories like collars, leashes, or pet clothing",
        "pet_toys": "a photo of pet toys, chew toys, or animal playthings",
        "pet_furniture": "a photo of pet furniture like cat trees, dog beds, or pet houses",
    }
    
    return [
        (s.id, s.label_en, subcategory_prompts_map.get(s.id, f"a photo of {main.label_en} {s.label_en}"))
        for s in main.subcategories
    ]


def get_allowed_tags_for_category(main_id: str) -> List[str]:
    """Return list of approved tag ids allowed for this category."""
    main = _MAIN_BY_ID.get(main_id)
    if not main:
        return []
    return list(main.allowed_tag_ids)


def get_all_tag_prompts() -> List[str]:
    """Return prompt string for each approved tag (for zero-shot)."""
    return list(APPROVED_TAGS)


# ── Normalization: raw model output → canonical internal value ────────────────

def normalize_category(raw: Optional[str]) -> Optional[str]:
    """Map raw prediction to canonical main category id, or None."""
    if not raw or not raw.strip():
        return None
    r = raw.strip().lower()
    if r in _MAIN_BY_ID:
        return r
    if r in _MAIN_BY_LABEL_LOWER:
        return _MAIN_BY_LABEL_LOWER[r].id
    # Try match on label containing
    for m in MAIN_CATEGORIES:
        if r in m.label_en.lower() or m.label_en.lower() in r:
            return m.id
    return None


def normalize_condition(raw: Optional[str]) -> Optional[str]:
    """Map raw to canonical condition value (new, like_new, good, fair, poor)."""
    if not raw or not raw.strip():
        return None
    r = raw.strip().lower().replace(" ", "_")
    if r in _CONDITION_BY_VALUE:
        return r
    if r in _CONDITION_LOWER:
        return _CONDITION_LOWER[r]
    return None


def normalize_tag(raw: Optional[str]) -> Optional[str]:
    """Map raw to canonical approved tag id, or None."""
    if not raw or not raw.strip():
        return None
    r = raw.strip().lower().replace(" ", "-")
    if r in APPROVED_TAGS:
        return r
    # Allow hyphen/underscore variants
    r2 = r.replace("_", "-")
    if r2 in APPROVED_TAGS:
        return r2
    return None


def filter_allowed_tags(
    predicted_tags: List[str], main_id: str, max_tags: int = 5
) -> List[str]:
    """Keep only approved tags that are allowed for this category, up to max_tags."""
    allowed = set(get_allowed_tags_for_category(main_id))
    out: List[str] = []
    for t in predicted_tags:
        if len(out) >= max_tags:
            break
        canonical = normalize_tag(t)
        if canonical and canonical in allowed and canonical not in out:
            out.append(canonical)
    return out


def normalize_tags(predicted_tags: List[str], main_id: Optional[str] = None) -> List[str]:
    """Normalize and optionally filter by category. Returns list of canonical tags."""
    normalized = []
    seen = set()
    for t in predicted_tags:
        c = normalize_tag(t)
        if c and c not in seen:
            if main_id is None or c in set(get_allowed_tags_for_category(main_id)):
                normalized.append(c)
                seen.add(c)
    return normalized


# ── Title generation ────────────────────────────────────────────────────────

def build_title(
    main_id: str,
    condition: str,
    tags: List[str],
    sub_id: Optional[str] = None,
    max_tags: int = 2,
) -> str:
    """Build title: [subcategory or category] - condition (tag1, tag2)."""
    main = _MAIN_BY_ID.get(main_id)
    if not main:
        category_part = main_id.replace("_", " ").title()
    elif sub_id:
        sub = next((s for s in main.subcategories if s.id == sub_id), None)
        category_part = f"{sub.label_en}" if sub else main.label_en
    else:
        category_part = main.label_en
    condition_label = condition.replace("_", " ")
    allowed = get_allowed_tags_for_category(main_id)
    useful = [t for t in tags if t in allowed][:max_tags]
    tag_part = ", ".join(useful) if useful else "household item"
    return f"{category_part} - {condition_label} ({tag_part})"
