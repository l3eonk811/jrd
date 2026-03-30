"""
Hardening tests: listing text embeddings (model, semantic text, service, indexer, freshness).
"""

from __future__ import annotations

import math
import pathlib
import struct
import sys
from typing import List
from unittest import mock

import pytest
from sqlalchemy import update

# Ensure ``backend/`` is on path when pytest cwd is repo root or ``tests/``.
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import app.domain.text_embedding_constants as text_embedding_constants
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
from app.models.item import (
    AdoptionDetails,
    Item,
    ItemStatus,
    ListingDomain,
    ListingType,
    ServiceDetails,
)
from app.models.tag import ItemTag, Tag
from app.models.user import User
from app.schemas.item import ItemUpdate
from app.services.item_service import update_item
from app.services.semantic_text import (
    build_semantic_text,
    compute_embedding_source_fingerprint,
    compute_semantic_text_hash,
    semantic_segments_from_tag_names,
)
from app.services.text_embedding_freshness import (
    is_text_embedding_stale,
    listing_has_current_text_embedding,
    listing_needs_text_embedding_index,
)
from app.services.text_embedding_providers import MockTextEmbeddingProvider, TextEmbeddingProvider
from app.services.text_embedding_service import (
    TextEmbeddingJobOutcome,
    TextEmbeddingService,
    generate_text_embedding_for_item,
    validate_provider_embedding_vector,
)
from tools.index_text_embeddings import run_text_embedding_index


def _valid_vector(seed: float = 0.01) -> List[float]:
    v = [seed] * TEXT_EMBEDDING_DIM
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


class TestTextEmbeddingModelPackUnpack:
    """Corrupted-read policy: ``get_text_embedding`` raises ``CorruptedTextEmbeddingStorageError`` if bytes exist but are invalid; ``None`` only when storage is NULL."""

    def test_round_trip_exact_bytes(self):
        item = Item()
        vec = _valid_vector()
        item.set_text_embedding(vec)
        assert len(item.text_embedding) == TEXT_EMBEDDING_PACKED_BYTES
        out = item.get_text_embedding()
        assert len(out) == TEXT_EMBEDDING_DIM
        assert all(math.isfinite(x) for x in out)
        assert abs(sum(x * x for x in out) - 1.0) < 1e-5

    def test_little_endian_explicit(self):
        item = Item()
        vec = _valid_vector(0.02)
        item.set_text_embedding(vec)
        manual = struct.pack(TEXT_EMBEDDING_STRUCT_FMT, *vec)
        assert item.text_embedding == manual

    def test_reject_none_vector(self):
        item = Item()
        with pytest.raises(InvalidTextEmbeddingVectorError, match="must not be None"):
            item.set_text_embedding(None)  # type: ignore[arg-type]

    def test_reject_wrong_length(self):
        item = Item()
        with pytest.raises(InvalidTextEmbeddingVectorError, match=f"expected {TEXT_EMBEDDING_DIM}"):
            item.set_text_embedding([0.0] * 10)

    def test_reject_nan_inf(self):
        item = Item()
        bad = _valid_vector()
        bad[0] = float("nan")
        with pytest.raises(InvalidTextEmbeddingVectorError, match="finite"):
            item.set_text_embedding(bad)
        bad2 = _valid_vector()
        bad2[0] = float("inf")
        with pytest.raises(InvalidTextEmbeddingVectorError):
            item.set_text_embedding(bad2)

    def test_get_none_when_missing(self):
        item = Item()
        assert item.get_text_embedding() is None

    def test_get_corrupted_wrong_length(self):
        item = Item()
        item.text_embedding = b"\x00" * 10
        with pytest.raises(CorruptedTextEmbeddingStorageError, match="expected"):
            item.get_text_embedding()

    def test_get_corrupted_non_finite(self):
        item = Item()
        vec = [0.0] * (TEXT_EMBEDDING_DIM - 1) + [float("inf")]
        item.text_embedding = struct.pack(TEXT_EMBEDDING_STRUCT_FMT, *vec)
        with pytest.raises(CorruptedTextEmbeddingStorageError):
            item.get_text_embedding()

    def test_clear_listing_text_embedding(self):
        item = Item()
        item.set_text_embedding(_valid_vector())
        item.semantic_text = "x"
        item.text_embedding_source_hash = "a" * 64
        item.clear_listing_text_embedding()
        assert item.text_embedding is None
        assert item.semantic_text is None
        assert item.text_embedding_source_hash is None
        assert item.text_embedding_updated_at is None


class TestSemanticTextDeterminism:
    def test_identical_across_runs(self):
        item = Item(title="  Hello   world  ", description="  x  ")
        assert build_semantic_text(item) == build_semantic_text(item)

    def test_prefixes_and_joiner(self):
        item = Item(title="A", category="B")
        s = build_semantic_text(item)
        assert s == "title:A | category:B"

    def test_whitespace_normalization(self):
        item = Item(title="  multi   line  \n  text ")
        assert "multi line text" in build_semantic_text(item)

    def test_tags_sorted_deduped(self):
        item = Item(title="t")
        z = Tag(name="zebra")
        a = Tag(name="apple")
        a2 = Tag(name="Apple")
        item.item_tags = [
            ItemTag(tag=z),
            ItemTag(tag=a),
            ItemTag(tag=a2),
        ]
        s = build_semantic_text(item)
        tag_segments = [p for p in s.split(" | ") if p.startswith("tag:")]
        assert len(tag_segments) == 2
        assert "tag:zebra" in s
        assert sum(1 for p in tag_segments if p.casefold().startswith("tag:apple")) == 1

    def test_tag_order_stable_when_collection_reordered(self):
        item1 = Item(title="x")
        t1, t2 = Tag(name="b"), Tag(name="a")
        item1.item_tags = [ItemTag(tag=t1), ItemTag(tag=t2)]
        item2 = Item(title="x")
        item2.item_tags = [ItemTag(tag=t2), ItemTag(tag=t1)]
        assert build_semantic_text(item1) == build_semantic_text(item2)

    def test_hash_stable(self):
        h1 = compute_semantic_text_hash("title:a | category:b")
        h2 = compute_semantic_text_hash("title:a | category:b")
        assert h1 == h2
        assert len(h1) == 64

    def test_semantic_segments_helper(self):
        assert semantic_segments_from_tag_names(["b", "a"]) == ["tag:a", "tag:b"]


class TestMockTextEmbeddingProvider:
    def test_deterministic(self):
        p = MockTextEmbeddingProvider()
        a = p.embed("hello semantic")
        b = p.embed("hello semantic")
        assert a == b
        assert len(a) == TEXT_EMBEDDING_DIM
        assert abs(sum(x * x for x in a) - 1.0) < 1e-5

    def test_empty_raises(self):
        with pytest.raises(EmptySemanticTextInputError):
            MockTextEmbeddingProvider().embed("")
        with pytest.raises(EmptySemanticTextInputError):
            MockTextEmbeddingProvider().embed("   ")

    def test_different_inputs_differ(self):
        p = MockTextEmbeddingProvider()
        assert p.embed("a") != p.embed("b")


class BadDimProvider(TextEmbeddingProvider):
    dim = 3

    def embed(self, text: str) -> List[float]:
        return [0.0, 0.0, 1.0]


class ExplodingProvider(MockTextEmbeddingProvider):
    def embed(self, text: str) -> List[float]:
        raise RuntimeError("provider exploded")


class TestTextEmbeddingServiceFacade:
    def test_rejects_provider_wrong_dim(self):
        with pytest.raises(InvalidTextEmbeddingVectorError, match="provider dim"):
            TextEmbeddingService(provider=BadDimProvider())


class TestValidateProviderEmbeddingVector:
    def test_wrong_length(self):
        with pytest.raises(InvalidTextEmbeddingVectorError, match=f"expected {TEXT_EMBEDDING_DIM}"):
            validate_provider_embedding_vector([0.0] * 10)

    def test_nan(self):
        v = _valid_vector()
        v[0] = float("nan")
        with pytest.raises(InvalidTextEmbeddingVectorError, match="finite"):
            validate_provider_embedding_vector(v)

    def test_inf(self):
        v = _valid_vector()
        v[0] = float("inf")
        with pytest.raises(InvalidTextEmbeddingVectorError, match="finite"):
            validate_provider_embedding_vector(v)


class WrongEmbedLenProvider(TextEmbeddingProvider):
    dim = TEXT_EMBEDDING_DIM

    def embed(self, text: str) -> List[float]:
        return [0.0] * 17


class NanOutProvider(TextEmbeddingProvider):
    dim = TEXT_EMBEDDING_DIM

    def embed(self, text: str) -> List[float]:
        v = _valid_vector()
        v[0] = float("nan")
        return v


class InfOutProvider(TextEmbeddingProvider):
    dim = TEXT_EMBEDDING_DIM

    def embed(self, text: str) -> List[float]:
        v = _valid_vector()
        v[3] = float("-inf")
        return v


class HijackMidEmbedProvider(MockTextEmbeddingProvider):
    """Simulate another writer changing semantic source during embed (same DB, second session)."""

    def __init__(self, db, item_id: int):
        super().__init__()
        self._db = db
        self._item_id = item_id
        self._armed = True

    def embed(self, text: str) -> List[float]:
        if self._armed:
            self._armed = False
            from sqlalchemy.orm import Session

            s2 = Session(bind=self._db.get_bind())
            row = s2.query(Item).filter(Item.id == self._item_id).first()
            row.title = "CHANGED_DURING_EMBED"
            s2.commit()
            s2.close()
        return super().embed(text)


class TestGenerateTextEmbeddingForItem:
    def test_success_and_timestamp(self, db):
        u = User(
            email="e1@example.com",
            username="u1",
            hashed_password="x",
        )
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Bike",
            description="good",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        svc = TextEmbeddingService()
        res = generate_text_embedding_for_item(db, it.id, service=svc, commit=True)
        assert res.outcome == TextEmbeddingJobOutcome.SUCCESS
        db.refresh(it)
        assert it.text_embedding is not None
        assert it.semantic_text
        assert it.text_embedding_source_hash == compute_embedding_source_fingerprint(it.semantic_text)
        assert it.text_embedding_updated_at is not None

    def test_skipped_empty_title_only_whitespace_fails_no_title(self, db):
        u = User(email="e2@example.com", username="u2", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title=" ",
            status=ItemStatus.draft.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        res = generate_text_embedding_for_item(db, it.id, commit=True)
        # title collapses to empty → no segments → SKIPPED_EMPTY
        assert res.outcome == TextEmbeddingJobOutcome.SKIPPED_EMPTY

    def test_idempotent_skip_when_current(self, db):
        u = User(email="e3@example.com", username="u3", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Chair",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        svc = TextEmbeddingService()
        assert generate_text_embedding_for_item(db, it.id, service=svc).outcome == TextEmbeddingJobOutcome.SUCCESS
        res2 = generate_text_embedding_for_item(db, it.id, service=svc, force=False)
        assert res2.outcome == TextEmbeddingJobOutcome.SKIPPED_ALREADY_CURRENT

    def test_force_regenerates(self, db):
        u = User(email="e4@example.com", username="u4", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Desk",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        svc = TextEmbeddingService()
        generate_text_embedding_for_item(db, it.id, service=svc)
        db.refresh(it)
        first = it.text_embedding
        generate_text_embedding_for_item(db, it.id, service=svc, force=True)
        db.refresh(it)
        assert it.text_embedding == first  # mock deterministic same semantic

    def test_provider_failure_no_timestamp(self, db):
        u = User(email="e5@example.com", username="u5", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Table",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        svc = TextEmbeddingService(provider=ExplodingProvider())
        res = generate_text_embedding_for_item(db, it.id, service=svc, commit=True)
        assert res.outcome == TextEmbeddingJobOutcome.FAILED_PROVIDER
        db.refresh(it)
        assert it.text_embedding is None
        assert it.text_embedding_updated_at is None

    def test_preloaded_item_mismatch(self, db):
        u = User(email="e6@example.com", username="u6", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Z",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        res = generate_text_embedding_for_item(
            db,
            99999,
            preloaded_item=it,
            commit=True,
        )
        assert res.outcome == TextEmbeddingJobOutcome.FAILED_STORAGE

    def test_provider_wrong_length_no_partial_state(self, db):
        u = User(email="e_wronglen@example.com", username="u_wronglen", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Wrong len",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        svc = TextEmbeddingService(provider=WrongEmbedLenProvider())
        res = generate_text_embedding_for_item(db, it.id, service=svc, commit=True)
        assert res.outcome == TextEmbeddingJobOutcome.FAILED_PROVIDER
        db.refresh(it)
        assert it.text_embedding is None
        assert it.text_embedding_source_hash is None
        assert it.text_embedding_updated_at is None

    def test_provider_nan_no_partial_state(self, db):
        u = User(email="e_nan@example.com", username="u_nan", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Nan out",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        svc = TextEmbeddingService(provider=NanOutProvider())
        res = generate_text_embedding_for_item(db, it.id, service=svc, commit=True)
        assert res.outcome == TextEmbeddingJobOutcome.FAILED_PROVIDER
        db.refresh(it)
        assert it.text_embedding is None

    def test_provider_inf_no_partial_state(self, db):
        u = User(email="e_inf@example.com", username="u_inf", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Inf out",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        svc = TextEmbeddingService(provider=InfOutProvider())
        res = generate_text_embedding_for_item(db, it.id, service=svc, commit=True)
        assert res.outcome == TextEmbeddingJobOutcome.FAILED_PROVIDER
        db.refresh(it)
        assert it.text_embedding is None

    def test_aborted_when_source_changes_during_embed(self, db):
        u = User(email="e_race@example.com", username="u_race", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="BEFORE_RACE",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        ok = TextEmbeddingService()
        assert generate_text_embedding_for_item(db, it.id, service=ok, commit=True).outcome == (
            TextEmbeddingJobOutcome.SUCCESS
        )
        db.refresh(it)
        hijack = TextEmbeddingService(provider=HijackMidEmbedProvider(db, it.id))
        res = generate_text_embedding_for_item(db, it.id, service=hijack, force=True, commit=True)
        assert res.outcome == TextEmbeddingJobOutcome.ABORTED_SOURCE_STALE
        db.refresh(it)
        assert it.title == "CHANGED_DURING_EMBED"
        # Parallel title change triggers Item invalidation; stale vector must not persist.
        assert it.text_embedding is None

    def test_clears_orphan_when_semantic_becomes_empty_bulk_bypass(self, db):
        u = User(email="e_orphan@example.com", username="u_orphan", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Has text",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        assert generate_text_embedding_for_item(db, it.id, commit=True).outcome == TextEmbeddingJobOutcome.SUCCESS
        db.refresh(it)
        assert it.text_embedding is not None
        db.execute(update(Item).where(Item.id == it.id).values(title="   "))
        db.commit()
        db.refresh(it)
        res = generate_text_embedding_for_item(db, it.id, commit=True)
        assert res.outcome == TextEmbeddingJobOutcome.CLEARED_ORPHAN_EMBEDDING
        db.refresh(it)
        assert it.text_embedding is None
        assert it.text_embedding_source_hash is None


class TestFreshnessAndInvalidation:
    def test_orm_description_change_clears_embedding(self, db):
        u = User(email="e7@example.com", username="u7", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Same",
            description="old",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert not is_text_embedding_stale(it)
        it.description = "new body"
        db.commit()
        db.refresh(it)
        assert it.text_embedding is None
        assert not is_text_embedding_stale(it)

    def test_stale_when_source_changed_via_bulk_bypass(self, db):
        u = User(email="e7b@example.com", username="u7b", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Same",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert not is_text_embedding_stale(it)
        db.execute(update(Item).where(Item.id == it.id).values(title="Changed title"))
        db.commit()
        db.refresh(it)
        assert it.text_embedding is not None
        assert is_text_embedding_stale(it)

    def test_bulk_sql_bypass_stale_blob_not_treated_as_current(self, db):
        u = User(email="e_bulk_gate@example.com", username="u_bulk_gate", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Before bulk",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        assert generate_text_embedding_for_item(db, it.id, commit=True).outcome == TextEmbeddingJobOutcome.SUCCESS
        db.refresh(it)
        assert listing_has_current_text_embedding(it)
        db.execute(update(Item).where(Item.id == it.id).values(title="After bulk"))
        db.commit()
        db.refresh(it)
        assert it.text_embedding is not None
        assert not listing_has_current_text_embedding(it)
        assert listing_needs_text_embedding_index(it)

    def test_stored_semantic_text_must_match_canonical_for_current_gate(self, db):
        u = User(email="e_sem_snap@example.com", username="u_sem_snap", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Consistent title",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        assert generate_text_embedding_for_item(db, it.id, commit=True).outcome == TextEmbeddingJobOutcome.SUCCESS
        db.refresh(it)
        canonical = build_semantic_text(it)
        assert it.semantic_text == canonical
        assert listing_has_current_text_embedding(it)
        it.semantic_text = "title:corrupt_snapshot_not_from_build"
        db.commit()
        db.refresh(it)
        assert it.text_embedding_source_hash == compute_embedding_source_fingerprint(canonical)
        assert build_semantic_text(it) == canonical
        assert not listing_has_current_text_embedding(it)
        assert listing_needs_text_embedding_index(it)

    def test_listing_needs_index(self, db):
        u = User(email="e8@example.com", username="u8", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Need me",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        db.refresh(it)
        assert listing_needs_text_embedding_index(it)
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert not listing_needs_text_embedding_index(it)

    def test_update_item_invalidates_embedding(self, db):
        u = User(
            email="e9@example.com",
            username="u9",
            hashed_password="x",
            is_email_verified=True,
        )
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Old",
            description="d",
            status=ItemStatus.draft.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert it.text_embedding is not None
        update_item(db, it.id, ItemUpdate(title="New title"), u)
        db.refresh(it)
        assert it.text_embedding is None
        assert it.text_embedding_source_hash is None

    def test_listing_needs_index_when_empty_semantic_but_blob_remains(self, db):
        u = User(email="e_needs@example.com", username="u_needs", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="X",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.execute(update(Item).where(Item.id == it.id).values(title="  "))
        db.commit()
        db.refresh(it)
        assert listing_needs_text_embedding_index(it)


class TestCentralizedInvalidationOutsideUpdateItem:
    """Listeners must clear embeddings for ORM writes that do not use ``update_item``."""

    def test_title_becomes_whitespace_clears_embedding_via_orm(self, db):
        u = User(email="e_ws@example.com", username="u_ws", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Solid",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert it.text_embedding is not None
        it.title = "   "
        db.commit()
        db.refresh(it)
        assert it.text_embedding is None

    def test_direct_orm_title_change_clears_embedding(self, db):
        u = User(email="e_c1@example.com", username="u_c1", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Alpha",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert it.text_embedding is not None
        it.title = "Beta"
        db.commit()
        db.refresh(it)
        assert it.text_embedding is None

    def test_item_tag_add_clears_without_update_item(self, db):
        u = User(email="e_c2@example.com", username="u_c2", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Tagged",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert it.text_embedding is not None
        tg = Tag(name="fresh")
        db.add(tg)
        db.flush()
        db.add(ItemTag(item_id=it.id, tag_id=tg.id))
        db.commit()
        db.refresh(it)
        assert it.text_embedding is None

    def test_service_category_change_clears(self, db):
        u = User(email="e_c3@example.com", username="u_c3", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Plumber",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.service.value,
            service_category="plumber",
        )
        db.add(it)
        db.flush()
        db.add(ServiceDetails(item_id=it.id, service_category="plumber"))
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert it.text_embedding is not None
        sd = db.query(ServiceDetails).filter(ServiceDetails.item_id == it.id).one()
        sd.service_category = "ac_technician"
        db.commit()
        db.refresh(it)
        assert it.text_embedding is None

    def test_adoption_animal_type_change_clears(self, db):
        u = User(email="e_c4@example.com", username="u_c4", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Pet",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
            listing_type=ListingType.adoption.value,
        )
        db.add(it)
        db.flush()
        db.add(AdoptionDetails(item_id=it.id, animal_type="dog"))
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert it.text_embedding is not None
        ad = db.query(AdoptionDetails).filter(AdoptionDetails.item_id == it.id).one()
        ad.animal_type = "cat"
        db.commit()
        db.refresh(it)
        assert it.text_embedding is None


class TestSemanticTextVersioning:
    def test_fingerprint_version_bump_marks_stale(self, db):
        u = User(email="e_ver@example.com", username="u_ver", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Versioned",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        assert not is_text_embedding_stale(it)
        with mock.patch.object(text_embedding_constants, "SEMANTIC_TEXT_FORMAT_VERSION", 4242):
            assert is_text_embedding_stale(it)


class TestIndexingScript:
    def test_run_empty_stats(self, db):
        stats = run_text_embedding_index(db, limit=0)
        assert stats.total_in_scope == 0
        assert stats.processed == 0

    def test_run_skip_and_update_counters(self, db):
        u = User(email="e10@example.com", username="u10", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Index me",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        s1 = run_text_embedding_index(db, force=False, batch_size=10)
        assert s1.updated >= 1
        s2 = run_text_embedding_index(db, force=False, batch_size=10)
        assert s2.skipped >= 1

    def test_run_force_updates(self, db):
        u = User(email="e11@example.com", username="u11", hashed_password="x")
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Force idx",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
        )
        db.add(it)
        db.commit()
        run_text_embedding_index(db, force=False)
        stats = run_text_embedding_index(db, force=True)
        assert stats.updated >= 1
