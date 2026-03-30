"""
Deterministic canonical text for listing text embeddings.

Definition (stable across runs and ORM collection order):
- UTF-8 NFC normalization per field fragment; trim; internal whitespace collapsed to single spaces.
- Segments (only non-empty) concatenated in fixed order with ``" | "`` (space-pipe-space).
- Prefixes (literal, lowercase key before colon): ``title``, ``category``, ``subcategory``,
  ``tag`` (one segment per tag), ``service_category``, ``animal_type``, ``description``.
- Tags: deduplicated by case-insensitive key (NFC lower), emitted sorted by that key; value is NFC-normalized name.

Identical listing content → identical ``semantic_text`` string (bitwise), excluding object identity.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Iterable

from app.domain import text_embedding_constants as _tec
from app.models.item import Item


def _collapse_ws(value: str) -> str:
    """Trim and collapse internal runs of whitespace (deterministic)."""
    s = unicodedata.normalize("NFC", value).strip()
    return " ".join(s.split()) if s else ""


def normalize_free_text_for_embedding_query(raw: str | None) -> str:
    """
    Normalize user search text before query embedding (Phase 2).

    Uses the same NFC + whitespace rules as semantic field fragments so provider
    input is stable and explicit; not the same as full ``build_semantic_text`` (no segments).
    """
    if raw is None:
        return ""
    return _collapse_ws(str(raw))


def build_semantic_text(item: Item) -> str:
    """
    Build canonical semantic text for ``item`` (order-stable, no randomness).

    Ignores None, empty, and whitespace-only field values. Omits missing optional relations.
    """
    segments: list[str] = []

    t = _collapse_ws(str(item.title)) if item.title else ""
    if t:
        segments.append(f"title:{t}")

    if item.category:
        c = _collapse_ws(str(item.category))
        if c:
            segments.append(f"category:{c}")

    if item.subcategory:
        sc = _collapse_ws(str(item.subcategory))
        if sc:
            segments.append(f"subcategory:{sc}")

    tag_names: list[str] = []
    for it in item.item_tags or []:
        tag = getattr(it, "tag", None)
        name = getattr(tag, "name", None) if tag is not None else None
        if name:
            collapsed = _collapse_ws(str(name))
            if collapsed:
                tag_names.append(collapsed)

    # Dedupe by case-insensitive NFC key; sort by key then tie-break on exact string
    seen: dict[str, str] = {}
    for nm in tag_names:
        key = unicodedata.normalize("NFC", nm).casefold()
        if key not in seen or nm < seen[key]:
            seen[key] = nm
    for canonical in sorted(seen.values(), key=lambda x: unicodedata.normalize("NFC", x).casefold()):
        segments.append(f"tag:{canonical}")

    sd = getattr(item, "service_details", None)
    if sd is not None and sd.service_category:
        svc = _collapse_ws(str(sd.service_category))
        if svc:
            segments.append(f"service_category:{svc}")

    ad = getattr(item, "adoption_details", None)
    if ad is not None and ad.animal_type:
        an = _collapse_ws(str(ad.animal_type))
        if an:
            segments.append(f"animal_type:{an}")

    if item.description:
        d = _collapse_ws(str(item.description))
        if d:
            segments.append(f"description:{d}")

    return " | ".join(segments)


def compute_semantic_text_hash(semantic_text: str) -> str:
    """
    SHA-256 hex digest of UTF-8 encoding of ``semantic_text`` (content only, no version).

    Used for diagnostics or content-only checks. **Stored freshness** uses
    ``compute_embedding_source_fingerprint`` so canonicalization rule changes invalidate rows.
    """
    return hashlib.sha256(semantic_text.encode("utf-8")).hexdigest()


def compute_embedding_source_fingerprint(semantic_text: str) -> str:
    """
    SHA-256 hex digest of format version, vector layout (``TEXT_EMBEDDING_DIM``), and canonical semantic content.

    Bump ``SEMANTIC_TEXT_FORMAT_VERSION`` in ``text_embedding_constants`` when
    ``build_semantic_text`` segment rules change so existing rows become stale without ad-hoc ops.
    Changing ``TEXT_EMBEDDING_DIM`` also changes this fingerprint (embedding model layout migration).
    """
    normalized = unicodedata.normalize("NFC", semantic_text).strip()
    # Include vector layout (dim) so upgrades from 384-dim blobs invalidate hashes safely.
    payload = f"v{_tec.SEMANTIC_TEXT_FORMAT_VERSION}\0dim={_tec.TEXT_EMBEDDING_DIM}\0{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def semantic_segments_from_tag_names(tag_names: Iterable[str]) -> list[str]:
    """Test helper: same tag normalization as build_semantic_text (sorted tag: segments)."""
    collapsed = [_collapse_ws(str(n)) for n in tag_names]
    collapsed = [x for x in collapsed if x]
    seen: dict[str, str] = {}
    for nm in collapsed:
        key = unicodedata.normalize("NFC", nm).casefold()
        if key not in seen or nm < seen[key]:
            seen[key] = nm
    return [
        f"tag:{canonical}"
        for canonical in sorted(seen.values(), key=lambda x: unicodedata.normalize("NFC", x).casefold())
    ]
