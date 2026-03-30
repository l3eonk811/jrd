"""
Stale detection for persisted listing text embeddings.

Runtime checks use ``listing_has_current_text_embedding`` so a non-NULL blob is never
treated as valid unless the persisted ``semantic_text`` column, the canonical build,
and the fingerprint are mutually consistent (safe when ORM invalidation was bypassed).
"""

from __future__ import annotations

from app.models.item import Item
from app.services.semantic_text import build_semantic_text, compute_embedding_source_fingerprint


def listing_has_current_text_embedding(item: Item) -> bool:
    """
    Return True ONLY if the stored embedding is valid and matches the current
    semantic source of the item.

    This must remain correct even if ORM listeners were bypassed (e.g. bulk/Core SQL).

    Requires ``items.semantic_text`` to equal ``build_semantic_text(item)`` so a correct
    fingerprint cannot mask a mismatched stored snapshot (manual SQL / partial writes).
    """
    if item.text_embedding is None:
        return False
    if item.text_embedding_source_hash is None:
        return False
    semantic = build_semantic_text(item)
    if not semantic or not semantic.strip():
        return False
    if item.semantic_text != semantic:
        return False
    expected = compute_embedding_source_fingerprint(semantic)
    return item.text_embedding_source_hash == expected


def is_text_embedding_stale(item: Item) -> bool:
    """
    Return True when a stored blob exists but is not current per
    ``listing_has_current_text_embedding`` (including orphan vectors and hash mismatch).

    False when there is no stored vector.
    """
    if item.text_embedding is None:
        return False
    return not listing_has_current_text_embedding(item)


def listing_needs_text_embedding_index(item: Item) -> bool:
    """
    True if the indexer should process this row.

    Explicit ``text_embedding_needs_reindex`` (set on create / semantic edits) forces a pass.

    If canonical semantic text is empty: True when any embedding residue exists
    (blob, hash, timestamp, or non-blank persisted ``semantic_text`` snapshot).

    Otherwise: True when ``listing_has_current_text_embedding`` is False.
    """
    if getattr(item, "text_embedding_needs_reindex", False):
        return True
    semantic = build_semantic_text(item)
    if not semantic:
        return (
            item.text_embedding is not None
            or item.text_embedding_source_hash is not None
            or item.text_embedding_updated_at is not None
            or (item.semantic_text is not None and str(item.semantic_text).strip() != "")
        )
    return not listing_has_current_text_embedding(item)
