"""
Condition estimation placeholder.

Condition is NOT inferred from the image yet. This module returns a fixed
default so the pipeline works end-to-end. Replace with a dedicated
condition classifier (e.g. fine-tuned on condition labels) when available.

Output values must match ItemCondition: new | like_new | good | fair | poor.
"""

from pathlib import Path

# Constant default: no visual inference; safe placeholder for MVP.
# Change this when plugging in a real condition model.
PLACEHOLDER_CONDITION = "good"

# Labels for a future condition classifier; map to ItemCondition.
CONDITION_LABELS = ["new", "used_good", "used_fair", "damaged", "needs_repair"]

LABEL_TO_CONDITION = {
    "new": "new",
    "used_good": "like_new",
    "used_fair": "fair",
    "damaged": "poor",
    "needs_repair": "poor",
}


def estimate_condition_from_image_path(image_path: Path) -> str:
    """
    Placeholder: returns a constant default. Condition is not visually inferred.

    The image path is accepted for API compatibility with a future classifier
    that will take (image_path) and return a real prediction. Replace this
    implementation with a model call when a condition classifier is available.
    """
    _ = image_path  # unused; kept for pluggable signature
    return PLACEHOLDER_CONDITION
