"""
Deterministic image classifier — the mock backbone for the AI pipeline.

How it works
------------
1.  The image file is opened with Pillow to read its real dimensions.
2.  A stable numeric seed is derived from:
      filename bytes + file size in bytes + width + height
    This means the *same image file* always produces the *same prediction*,
    which is essential for reproducible development and testing.
3.  The seed drives all random choices (category → title → tags → condition).
4.  Image geometry provides a lightweight heuristic:
      portrait  (h > w)  →  bias toward Clothing, Books, Art
      landscape (w > h)  →  bias toward Electronics, Furniture, Sports
      square            →  no bias
5.  File size provides a "quality" proxy for condition:
      < 100 KB   →  fair / poor
      100–500 KB →  good
      > 500 KB   →  like_new / new

Extending to OpenCLIP
---------------------
Replace `classify()` with an async CLIP forward pass:
  - Use `taxonomy.CATEGORIES[cat].keywords` as the zero-shot text prompts.
  - Map the nearest cosine-similarity text match to a category.
  - Map brightness / saturation statistics to condition.
The `AIClassificationInput` / `AIClassificationOutput` contracts stay the same.
"""

import hashlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

try:
    from PIL import Image as PILImage
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False

from app.ai.taxonomy import (
    CATEGORIES,
    CATEGORY_NAMES,
    CONDITIONS,
    CONDITION_VALUES,
    GLOBAL_TAGS,
)


# ── Data contracts ────────────────────────────────────────────────────────────

@dataclass
class AIClassificationInput:
    """Everything the classifier needs about an image."""
    path: Path
    file_size_bytes: int
    width: int
    height: int
    filename: str


@dataclass
class AIClassificationOutput:
    """Raw classifier output before it becomes an AIAnalysisResult."""
    title: str
    category: str
    condition: str
    smart_tags: List[str]
    description: str
    confidence: float
    input_width: int
    input_height: int
    input_file_size_bytes: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stable_seed(inp: AIClassificationInput) -> int:
    """Derive a stable integer seed from image identity."""
    raw = f"{inp.filename}|{inp.file_size_bytes}|{inp.width}|{inp.height}"
    digest = hashlib.sha256(raw.encode()).digest()
    # Use first 8 bytes → 64-bit integer
    return int.from_bytes(digest[:8], "big")


def _geometry_biased_category_weights(width: int, height: int) -> List[float]:
    """
    Return a weight vector over CATEGORY_NAMES, biased by image aspect ratio.
    Portrait → clothing / books / art.
    Landscape → electronics / furniture / sports.
    Square → uniform.
    """
    base = [1.0] * len(CATEGORY_NAMES)
    if width == 0 or height == 0:
        return base

    ratio = width / height  # > 1 = landscape, < 1 = portrait

    boosts: dict = {}
    if ratio < 0.8:  # portrait
        boosts = {"Clothing": 2.5, "Books": 2.0, "Home & Decor": 1.8}
    elif ratio > 1.2:  # landscape
        boosts = {"Electronics": 2.5, "Furniture": 2.0, "Sports & Outdoors": 1.8, "Kitchen": 1.5}

    for i, name in enumerate(CATEGORY_NAMES):
        base[i] *= boosts.get(name, 1.0)

    return base


def _size_biased_condition_weights(file_size_bytes: int) -> List[float]:
    """
    Simulate quality detection via file size.
    Larger, higher-resolution uploads → better condition.
    """
    kb = file_size_bytes / 1024
    if kb < 80:
        # low-res → old / worn
        weights = [0.5, 0.8, 1.5, 2.0, 2.5]
    elif kb < 300:
        weights = [1.0, 1.5, 2.5, 1.5, 0.8]
    elif kb < 1000:
        weights = [2.0, 3.0, 2.0, 0.8, 0.3]
    else:
        # large, high-quality photo
        weights = [3.0, 3.5, 1.5, 0.5, 0.2]

    return weights  # aligned with CONDITION_VALUES order


# ── Public API ────────────────────────────────────────────────────────────────

def read_image_input(image_path: Path) -> AIClassificationInput:
    """
    Read image metadata from disk.
    Falls back to (0, 0) dimensions if Pillow is unavailable.
    """
    size_bytes = image_path.stat().st_size
    width, height = 0, 0

    if _PILLOW_AVAILABLE:
        try:
            with PILImage.open(image_path) as img:
                width, height = img.size
        except Exception:
            pass  # malformed image — fall back to geometry-blind mode

    return AIClassificationInput(
        path=image_path,
        file_size_bytes=size_bytes,
        width=width,
        height=height,
        filename=image_path.name,
    )


def classify(inp: AIClassificationInput) -> AIClassificationOutput:
    """
    Run the deterministic mock classifier.

    This is a synchronous CPU-only function.
    The async wrapper in MockAIService calls it via `asyncio.to_thread`
    so it doesn't block the event loop.
    """
    seed = _stable_seed(inp)
    rng = random.Random(seed)

    # ── Category selection ────────────────────────────────────────────────
    category_weights = _geometry_biased_category_weights(inp.width, inp.height)
    category = rng.choices(CATEGORY_NAMES, weights=category_weights, k=1)[0]
    cat_def = CATEGORIES[category]

    # ── Title ─────────────────────────────────────────────────────────────
    title = rng.choice(cat_def.titles)

    # ── Condition ─────────────────────────────────────────────────────────
    condition_weights = _size_biased_condition_weights(inp.file_size_bytes)
    condition = rng.choices(CONDITION_VALUES, weights=condition_weights, k=1)[0]

    # ── Smart tags ────────────────────────────────────────────────────────
    # 2–3 category-specific tags + 0–1 global tag
    n_cat_tags = rng.randint(2, min(3, len(cat_def.tags)))
    cat_tags = rng.sample(cat_def.tags, k=n_cat_tags)

    global_tag: List[str] = []
    if rng.random() < 0.4:
        global_tag = [rng.choice(GLOBAL_TAGS)]

    smart_tags = cat_tags + global_tag

    # ── Confidence ────────────────────────────────────────────────────────
    # Mock confidence: higher for larger images (more "information")
    kb = inp.file_size_bytes / 1024
    base_conf = min(0.65 + (kb / 2000), 0.96)
    confidence = round(base_conf + rng.uniform(-0.03, 0.03), 3)

    # ── Description ──────────────────────────────────────────────────────
    cond_label = next(c.label for c in CONDITIONS if c.value == condition)
    description = (
        f"Detected a {cond_label.lower()}-condition {title.lower()}. "
        f"Category: {category}. "
        f"Image size: {inp.width}×{inp.height}px, {inp.file_size_bytes // 1024} KB."
    )

    return AIClassificationOutput(
        title=title,
        category=category,
        condition=condition,
        smart_tags=smart_tags,
        description=description,
        confidence=confidence,
        input_width=inp.width,
        input_height=inp.height,
        input_file_size_bytes=inp.file_size_bytes,
    )
