"""
Structured service listing categories (English keys only; labels are client-side).

Used for ``Item.service_category`` and ``ServiceDetails.service_category`` (same value).
"""

from __future__ import annotations

from typing import FrozenSet

# Controlled vocabulary — store exactly these strings in the database.
SERVICE_CATEGORY_KEYS: FrozenSet[str] = frozenset(
    (
        "teacher",
        "delivery_driver",
        "electrician",
        "ac_technician",
        "plumber",
        "government_services",
        "babysitter",
        "carpenter",
        "construction",
        "security_guard",
        "events",
        "photographer",
        "barista",
        "other",
    )
)


def is_valid_service_category(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip() in SERVICE_CATEGORY_KEYS


def assert_valid_service_category(value: str) -> str:
    """Return stripped canonical key or raise ValueError."""
    s = (value or "").strip()
    if s not in SERVICE_CATEGORY_KEYS:
        raise ValueError(
            f"service_category must be one of: {', '.join(sorted(SERVICE_CATEGORY_KEYS))}"
        )
    return s


def normalize_legacy_service_category(raw: str | None) -> str:
    """
    Map legacy free-text ``service_details.service_category`` values to a canonical key.
    Unknown / empty → ``other`` (backward compatible reads and PATCH merge).
    """
    if not raw:
        return "other"
    s = raw.strip()
    if s in SERVICE_CATEGORY_KEYS:
        return s
    return "other"
