#!/usr/bin/env python3
"""
Backfill or refresh ``items.text_embedding`` (listing text semantics only).

Default run processes rows that need work: ``text_embedding_needs_reindex`` and/or
legacy ``listing_needs_text_embedding_index`` (missing/stale embedding). Does not
touch ``image_embedding``.

  cd backend && python -m tools.index_text_embeddings
  cd backend && python -m tools.index_text_embeddings --force
  cd backend && python -m tools.index_text_embeddings --start-id 100 --limit 500 --batch-size 50

Uses DATABASE_URL from app settings.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.item import Item
from app.services.item_service import _item_options
from app.services.text_embedding_freshness import listing_needs_text_embedding_index
from app.services.text_embedding_service import (
    TextEmbeddingJobOutcome,
    TextEmbeddingService,
    generate_text_embedding_for_item,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _chunks(ids: List[int], size: int) -> Iterator[List[int]]:
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


@dataclass
class IndexTextEmbeddingsStats:
    """Counters for one indexer run (explicit; no silent drops)."""

    total_in_scope: int = 0
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    cleared_empty: int = 0
    aborted_stale: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)

    def record(self, outcome: TextEmbeddingJobOutcome) -> None:
        key = outcome.value
        self.outcomes[key] = self.outcomes.get(key, 0) + 1
        self.processed += 1
        if outcome == TextEmbeddingJobOutcome.SUCCESS:
            self.updated += 1
        elif outcome == TextEmbeddingJobOutcome.CLEARED_ORPHAN_EMBEDDING:
            self.cleared_empty += 1
        elif outcome == TextEmbeddingJobOutcome.ABORTED_SOURCE_STALE:
            self.aborted_stale += 1
        elif outcome in (
            TextEmbeddingJobOutcome.SKIPPED_EMPTY,
            TextEmbeddingJobOutcome.SKIPPED_ALREADY_CURRENT,
        ):
            self.skipped += 1
        else:
            self.failed += 1

    def record_indexer_skip_fresh_gate(self) -> None:
        """Row skipped: ``not force`` and ``not listing_needs_text_embedding_index``."""
        key = "indexer_skip_fresh_gate"
        self.outcomes[key] = self.outcomes.get(key, 0) + 1
        self.processed += 1
        self.skipped += 1


def run_text_embedding_index(
    db: Session,
    *,
    force: bool = False,
    start_id: int = 1,
    limit: Optional[int] = None,
    batch_size: int = 100,
    service: Optional[TextEmbeddingService] = None,
) -> IndexTextEmbeddingsStats:
    """
    Deterministic ordering by ``Item.id`` ascending; batched loads with ``joinedload`` (no N+1).
    """
    stats = IndexTextEmbeddingsStats()
    impl = service or TextEmbeddingService()

    q = db.query(Item.id).filter(Item.id >= start_id).order_by(Item.id.asc())
    id_rows = q.all()
    ids = [r[0] for r in id_rows]
    if limit is not None:
        ids = ids[:limit]
    stats.total_in_scope = len(ids)

    log.info(
        "text_embedding_index_start total_in_scope=%s force=%s start_id=%s batch_size=%s",
        stats.total_in_scope,
        force,
        start_id,
        batch_size,
    )

    for batch in _chunks(ids, max(1, batch_size)):
        rows = (
            db.query(Item)
            .options(*_item_options())
            .filter(Item.id.in_(batch))
            .all()
        )
        by_id = {it.id: it for it in rows}
        for iid in batch:
            item = by_id.get(iid)
            if item is None:
                log.error("text_embedding_index item_id=%s stage=batch_load outcome=missing_row", iid)
                stats.processed += 1
                stats.failed += 1
                stats.outcomes["missing_row"] = stats.outcomes.get("missing_row", 0) + 1
                continue
            if not force and not listing_needs_text_embedding_index(item):
                log.info("text_embedding_index item_id=%s outcome=indexer_skip_fresh_gate", iid)
                stats.record_indexer_skip_fresh_gate()
                continue
            res = generate_text_embedding_for_item(
                db,
                iid,
                service=impl,
                force=force,
                commit=True,
                preloaded_item=item,
            )
            log.info(
                "text_embedding_index item_id=%s outcome=%s detail=%s",
                iid,
                res.outcome.value,
                res.detail[:120] if res.detail else "",
            )
            stats.record(res.outcome)

    log.info(
        "text_embedding_index_done total_in_scope=%s processed=%s updated=%s skipped=%s failed=%s "
        "cleared_empty=%s aborted_stale=%s breakdown=%s",
        stats.total_in_scope,
        stats.processed,
        stats.updated,
        stats.skipped,
        stats.failed,
        stats.cleared_empty,
        stats.aborted_stale,
        stats.outcomes,
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Index text embeddings for items")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even when embedding matches current semantic hash",
    )
    parser.add_argument("--start-id", type=int, default=1, help="Minimum item id (inclusive)")
    parser.add_argument("--limit", type=int, default=None, help="Max items to process from scope")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="IDs per batched ORM load (joinedload)",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        run_text_embedding_index(
            db,
            force=args.force,
            start_id=args.start_id,
            limit=args.limit,
            batch_size=args.batch_size,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
