"""
Listing text embedding orchestration (separate from ``embedding_service`` image/OpenCLIP path).
"""

from __future__ import annotations

import logging
import math
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.text_embedding_constants import (
    TEXT_EMBEDDING_DIM,
    TEXT_EMBEDDING_PACKED_BYTES,
    TEXT_EMBEDDING_STRUCT_FMT,
)
from app.domain.text_embedding_errors import (
    CorruptedTextEmbeddingStorageError,
    EmptySemanticTextInputError,
    InvalidTextEmbeddingVectorError,
)
from app.models.item import Item
from app.services.item_service import _item_options
from app.services.semantic_text import build_semantic_text, compute_embedding_source_fingerprint
from app.services.text_embedding_freshness import listing_has_current_text_embedding
from app.services.text_embedding_provider_factory import get_shared_text_embedding_provider
from app.services.text_embedding_providers import TextEmbeddingProvider
from app.services.text_embedding_reindex import (
    clear_item_text_embedding_pending_reindex,
    mark_item_text_embedding_pending_reindex,
)

logger = logging.getLogger(__name__)


class TextEmbeddingJobOutcome(str, Enum):
    SUCCESS = "success"
    SKIPPED_EMPTY = "skipped_empty"
    SKIPPED_ALREADY_CURRENT = "skipped_already_current"
    CLEARED_ORPHAN_EMBEDDING = "cleared_orphan_embedding_empty_semantic"
    ABORTED_SOURCE_STALE = "aborted_source_stale_during_embed"
    FAILED_NOT_FOUND = "failed_not_found"
    FAILED_PROVIDER = "failed_provider"
    FAILED_STORAGE = "failed_storage"


@dataclass(frozen=True)
class TextEmbeddingJobResult:
    outcome: TextEmbeddingJobOutcome
    item_id: int
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == TextEmbeddingJobOutcome.SUCCESS


def validate_provider_embedding_vector(vector: object) -> None:
    """
    Reject provider output before any ORM write.

    Trust boundary: never persist without exact dim, finite floats, and correct packed size.
    Raises:
        InvalidTextEmbeddingVectorError: any violation (wrong length, non-finite, bad pack size).
    """
    if vector is None:
        raise InvalidTextEmbeddingVectorError("provider returned None instead of a vector")
    if not isinstance(vector, list):
        raise InvalidTextEmbeddingVectorError(
            f"provider returned {type(vector).__name__}, expected list[float]"
        )
    if len(vector) != TEXT_EMBEDDING_DIM:
        raise InvalidTextEmbeddingVectorError(
            f"expected {TEXT_EMBEDDING_DIM} floats from provider, got {len(vector)}"
        )
    validated: list[float] = []
    for i, x in enumerate(vector):
        try:
            f = float(x)
        except (TypeError, ValueError) as e:
            raise InvalidTextEmbeddingVectorError(
                f"element {i} is not float-convertible: {type(x).__name__}"
            ) from e
        if not math.isfinite(f):
            raise InvalidTextEmbeddingVectorError(f"element {i} is not finite: {f!r}")
        validated.append(f)
    packed = struct.pack(TEXT_EMBEDDING_STRUCT_FMT, *validated)
    if len(packed) != TEXT_EMBEDDING_PACKED_BYTES:
        raise InvalidTextEmbeddingVectorError(
            f"packed size {len(packed)} != expected {TEXT_EMBEDDING_PACKED_BYTES}"
        )


def _reassert_pending_after_rollback(db: Session, item_id: int, commit: bool) -> None:
    """After a failed persist, ensure the row stays marked for a later indexer pass."""
    fresh = db.query(Item).filter(Item.id == item_id).first()
    if fresh is None:
        return
    mark_item_text_embedding_pending_reindex(fresh)
    if not commit:
        return
    try:
        db.commit()
    except Exception:
        db.rollback()


class TextEmbeddingService:
    """Facade over a ``TextEmbeddingProvider`` (default: deterministic mock)."""

    def __init__(self, provider: Optional[TextEmbeddingProvider] = None) -> None:
        self._provider = provider or get_shared_text_embedding_provider()
        if self._provider.dim != TEXT_EMBEDDING_DIM:
            raise InvalidTextEmbeddingVectorError(
                f"provider dim {self._provider.dim} != TEXT_EMBEDDING_DIM {TEXT_EMBEDDING_DIM}"
            )

    @property
    def provider(self) -> TextEmbeddingProvider:
        return self._provider

    def generate_embedding(self, text: str) -> list[float]:
        """Delegate to provider (raises ``EmptySemanticTextInputError`` on empty input)."""
        return self._provider.embed_listing_text(text)


def generate_text_embedding_for_item(
    db: Session,
    item_id: int,
    *,
    service: Optional[TextEmbeddingService] = None,
    force: bool = False,
    commit: bool = True,
    preloaded_item: Optional[Item] = None,
) -> TextEmbeddingJobResult:
    """
    Rebuild semantic text from ORM, embed, persist atomically on success.

    Idempotent when ``force`` is False: skips if embedding exists and is not stale.

    **Empty semantic invariant:** no embedding bytes or success metadata may remain when
    canonical semantic text is empty or whitespace-only. Orphan vectors are cleared with
    outcome ``CLEARED_ORPHAN_EMBEDDING``.

    **Stale-write guard:** after ``embed()`` and vector validation, semantic text is re-read
    from the DB (expired ORM state) and compared to the snapshot used for embedding; if it
    changed, the write is aborted (``ABORTED_SOURCE_STALE``) so an old vector is never committed
    as current.

    On provider validation failure: no ORM mutation in that job (no partial success metadata).

    On storage failure after mutation attempt: rolls back this session transaction segment.
    """
    impl = service or TextEmbeddingService()
    stage = "load"

    try:
        if preloaded_item is not None:
            if preloaded_item.id != item_id:
                logger.error(
                    "text_embedding job item_id=%s preloaded_id_mismatch=%s",
                    item_id,
                    preloaded_item.id,
                )
                return TextEmbeddingJobResult(
                    TextEmbeddingJobOutcome.FAILED_STORAGE,
                    item_id,
                    "preloaded_item.id mismatch",
                )
            item = preloaded_item
        else:
            item = (
                db.query(Item)
                .options(*_item_options())
                .filter(Item.id == item_id)
                .first()
            )
        if item is None:
            logger.warning(
                "text_embedding job item_id=%s stage=%s outcome=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.FAILED_NOT_FOUND.value,
            )
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.FAILED_NOT_FOUND,
                item_id,
                "item not found",
            )

        stage = "semantic_text"
        semantic = build_semantic_text(item)
        if not semantic:
            has_payload = (
                item.text_embedding is not None
                or item.text_embedding_source_hash is not None
                or item.text_embedding_updated_at is not None
                or (item.semantic_text is not None and str(item.semantic_text).strip() != "")
            )
            if has_payload:
                item.clear_listing_text_embedding()
                clear_item_text_embedding_pending_reindex(item)
                try:
                    if commit:
                        db.commit()
                except Exception as e:
                    db.rollback()
                    logger.exception(
                        "text_embedding job item_id=%s stage=%s outcome=%s",
                        item_id,
                        stage,
                        TextEmbeddingJobOutcome.FAILED_STORAGE.value,
                    )
                    return TextEmbeddingJobResult(
                        TextEmbeddingJobOutcome.FAILED_STORAGE,
                        item_id,
                        f"{type(e).__name__}: {e}",
                    )
                logger.info(
                    "text_embedding job item_id=%s stage=%s outcome=%s",
                    item_id,
                    stage,
                    TextEmbeddingJobOutcome.CLEARED_ORPHAN_EMBEDDING.value,
                )
                return TextEmbeddingJobResult(
                    TextEmbeddingJobOutcome.CLEARED_ORPHAN_EMBEDDING,
                    item_id,
                    "cleared embedding; canonical semantic empty",
                )
            clear_item_text_embedding_pending_reindex(item)
            try:
                if commit:
                    db.commit()
            except Exception as e:
                db.rollback()
                logger.exception(
                    "text_embedding job item_id=%s stage=%s outcome=%s",
                    item_id,
                    stage,
                    TextEmbeddingJobOutcome.FAILED_STORAGE.value,
                )
                return TextEmbeddingJobResult(
                    TextEmbeddingJobOutcome.FAILED_STORAGE,
                    item_id,
                    f"{type(e).__name__}: {e}",
                )
            logger.info(
                "text_embedding job item_id=%s stage=%s outcome=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.SKIPPED_EMPTY.value,
            )
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.SKIPPED_EMPTY,
                item_id,
                "empty canonical semantic text",
            )

        stage = "freshness_check"
        if not force and listing_has_current_text_embedding(item):
            clear_item_text_embedding_pending_reindex(item)
            try:
                if commit:
                    db.commit()
            except Exception as e:
                db.rollback()
                logger.exception(
                    "text_embedding job item_id=%s stage=%s outcome=%s",
                    item_id,
                    stage,
                    TextEmbeddingJobOutcome.FAILED_STORAGE.value,
                )
                return TextEmbeddingJobResult(
                    TextEmbeddingJobOutcome.FAILED_STORAGE,
                    item_id,
                    f"{type(e).__name__}: {e}",
                )
            logger.info(
                "text_embedding job item_id=%s stage=%s outcome=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.SKIPPED_ALREADY_CURRENT.value,
            )
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.SKIPPED_ALREADY_CURRENT,
                item_id,
                "embedding matches current source fingerprint",
            )

        stage = "provider_embed"
        try:
            vector = impl.generate_embedding(semantic)
        except EmptySemanticTextInputError as e:
            logger.warning(
                "text_embedding job item_id=%s stage=%s outcome=%s error_type=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.FAILED_PROVIDER.value,
                type(e).__name__,
            )
            mark_item_text_embedding_pending_reindex(item)
            try:
                if commit:
                    db.commit()
            except Exception:
                db.rollback()
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.FAILED_PROVIDER,
                item_id,
                str(e),
            )
        except Exception as e:
            logger.exception(
                "text_embedding job item_id=%s stage=%s outcome=%s error_type=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.FAILED_PROVIDER.value,
                type(e).__name__,
            )
            mark_item_text_embedding_pending_reindex(item)
            try:
                if commit:
                    db.commit()
            except Exception:
                db.rollback()
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.FAILED_PROVIDER,
                item_id,
                f"{type(e).__name__}: {e}",
            )

        stage = "validate_vector"
        try:
            validate_provider_embedding_vector(vector)
        except InvalidTextEmbeddingVectorError as e:
            logger.error(
                "text_embedding job item_id=%s stage=%s outcome=%s detail=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.FAILED_PROVIDER.value,
                e,
            )
            mark_item_text_embedding_pending_reindex(item)
            try:
                if commit:
                    db.commit()
            except Exception:
                db.rollback()
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.FAILED_PROVIDER,
                item_id,
                str(e),
            )

        stage = "pre_commit_guard"
        db.expire(item)
        semantic_now = build_semantic_text(item)
        if semantic_now != semantic:
            logger.warning(
                "text_embedding job item_id=%s stage=%s outcome=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.ABORTED_SOURCE_STALE.value,
            )
            mark_item_text_embedding_pending_reindex(item)
            try:
                if commit:
                    db.commit()
            except Exception:
                db.rollback()
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.ABORTED_SOURCE_STALE,
                item_id,
                "semantic text changed during embed; refusing stale write",
            )

        stage = "persist"
        try:
            item.semantic_text = semantic_now
            item.set_text_embedding(vector)
            item.text_embedding_source_hash = compute_embedding_source_fingerprint(semantic_now)
            item.text_embedding_updated_at = datetime.now(timezone.utc)
            clear_item_text_embedding_pending_reindex(item)
            if commit:
                db.commit()
        except (InvalidTextEmbeddingVectorError, CorruptedTextEmbeddingStorageError) as e:
            db.rollback()
            logger.exception(
                "text_embedding job item_id=%s stage=%s outcome=%s error_type=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.FAILED_STORAGE.value,
                type(e).__name__,
            )
            _reassert_pending_after_rollback(db, item_id, commit)
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.FAILED_STORAGE,
                item_id,
                str(e),
            )
        except Exception as e:
            db.rollback()
            logger.exception(
                "text_embedding job item_id=%s stage=%s outcome=%s error_type=%s",
                item_id,
                stage,
                TextEmbeddingJobOutcome.FAILED_STORAGE.value,
                type(e).__name__,
            )
            _reassert_pending_after_rollback(db, item_id, commit)
            return TextEmbeddingJobResult(
                TextEmbeddingJobOutcome.FAILED_STORAGE,
                item_id,
                f"{type(e).__name__}: {e}",
            )

        logger.info(
            "text_embedding job item_id=%s stage=commit outcome=%s",
            item_id,
            TextEmbeddingJobOutcome.SUCCESS.value,
        )
        return TextEmbeddingJobResult(TextEmbeddingJobOutcome.SUCCESS, item_id, "ok")

    except Exception as e:
        try:
            db.rollback()
        except Exception:
            logger.exception("text_embedding rollback failed item_id=%s", item_id)
        logger.exception(
            "text_embedding job item_id=%s stage=%s outcome=unexpected error_type=%s",
            item_id,
            stage,
            type(e).__name__,
        )
        _reassert_pending_after_rollback(db, item_id, commit)
        return TextEmbeddingJobResult(
            TextEmbeddingJobOutcome.FAILED_STORAGE,
            item_id,
            f"{type(e).__name__}: {e}",
        )
