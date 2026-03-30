"""Map persisted ``Item.status`` + ``is_public`` to canonical listing lifecycle labels.

The database keeps the existing ``ItemStatus`` enum and ``is_public`` flag; this module is the
single place that defines how those fields express the product lifecycle:

- **draft** — not offered on the marketplace
- **published** — live for discovery (subject to search filters)
- **hidden** — exists but not publicly discoverable
- **archived** — retained history, not active
- **deleted** — withdrawn (``removed`` status)

Legacy status values (``available``, ``reserved``, ``donated``) remain stored as-is; they map
to published/hidden using visibility, not a global rename.
"""

from __future__ import annotations

from typing import Literal

CanonicalListingLifecycle = Literal["draft", "published", "hidden", "archived", "deleted"]


def canonical_listing_lifecycle(status: str, is_public: bool) -> CanonicalListingLifecycle:
    s = (status or "").strip().lower()
    if s == "draft":
        return "draft"
    if s == "removed":
        return "deleted"
    if s == "archived":
        return "archived"
    if s in ("available", "reserved", "donated"):
        return "published" if is_public else "hidden"
    return "hidden"
