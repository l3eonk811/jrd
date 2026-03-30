"""
Explicit pending state for listing text embedding (reindex) jobs.

Not used for image embeddings. Indexer and ``generate_text_embedding_for_item`` keep flags consistent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.item import Item


def mark_item_text_embedding_pending_reindex(item: Item) -> None:
    """Mark listing as needing a text-embedding job (does not commit)."""
    item.text_embedding_needs_reindex = True
    item.text_embedding_reindex_requested_at = datetime.now(timezone.utc)


def clear_item_text_embedding_pending_reindex(item: Item) -> None:
    """Clear pending state after a successful index or when nothing remains to embed."""
    item.text_embedding_needs_reindex = False
    item.text_embedding_reindex_requested_at = None


def count_listings_pending_text_embedding_reindex(db: Session) -> int:
    """Count rows with ``text_embedding_needs_reindex`` set (operational metric)."""
    return (
        db.query(func.count(Item.id))
        .filter(Item.text_embedding_needs_reindex.is_(True))
        .scalar()
        or 0
    )


def sample_listing_ids_pending_text_embedding_reindex(db: Session, *, limit: int = 50) -> List[int]:
    """Return up to ``limit`` item ids that still need reindex (ordered by id)."""
    lim = max(1, min(int(limit), 500))
    rows = (
        db.query(Item.id)
        .filter(Item.text_embedding_needs_reindex.is_(True))
        .order_by(Item.id.asc())
        .limit(lim)
        .all()
    )
    return [r[0] for r in rows]
