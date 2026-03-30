"""
Explicit text_embedding_needs_reindex flag: create/update vs indexer job.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.models.item import Item, ItemStatus, ListingDomain, ListingType
from app.models.user import User
from app.schemas.item import ItemCreate, ItemUpdate
from app.services.item_service import create_item, update_item
from app.services.text_embedding_providers import MockTextEmbeddingProvider
from app.services.text_embedding_reindex import (
    count_listings_pending_text_embedding_reindex,
    sample_listing_ids_pending_text_embedding_reindex,
)
from app.services.text_embedding_service import (
    TextEmbeddingJobOutcome,
    TextEmbeddingService,
    generate_text_embedding_for_item,
)


class ExplodingProvider(MockTextEmbeddingProvider):
    def embed(self, text: str) -> List[float]:
        raise RuntimeError("boom")


class TestExplicitReindexFlags:
    def test_create_marks_pending_reindex(self, db):
        u = User(email="re1@ex.com", username="re1", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        payload = ItemCreate(
            title="New listing",
            description="Body",
            is_public=False,
            listing_domain=ListingDomain.item,
            listing_type=ListingType.sale,
            price=50.0,
        )
        item = create_item(db, payload, u)
        assert item.text_embedding_needs_reindex is True
        assert item.text_embedding_reindex_requested_at is not None

    def test_semantic_update_marks_pending_after_indexed(self, db):
        u = User(email="re2@ex.com", username="re2", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        item = create_item(
            db,
            ItemCreate(
                title="Indexed title",
                is_public=False,
                listing_domain=ListingDomain.item,
                listing_type=ListingType.sale,
                price=40.0,
            ),
            u,
        )
        assert item.text_embedding_needs_reindex is True
        svc = TextEmbeddingService()
        assert generate_text_embedding_for_item(db, item.id, service=svc, commit=True).outcome == (
            TextEmbeddingJobOutcome.SUCCESS
        )
        db.refresh(item)
        assert item.text_embedding_needs_reindex is False
        update_item(db, item.id, ItemUpdate(title="Changed title"), u)
        db.refresh(item)
        assert item.text_embedding_needs_reindex is True
        assert item.text_embedding is None

    def test_price_only_update_does_not_set_pending_when_no_semantic_change(self, db):
        u = User(email="re3@ex.com", username="re3", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        item = create_item(
            db,
            ItemCreate(
                title="Stable",
                is_public=False,
                listing_domain=ListingDomain.item,
                listing_type=ListingType.sale,
                price=10.0,
            ),
            u,
        )
        svc = TextEmbeddingService()
        assert generate_text_embedding_for_item(db, item.id, service=svc, commit=True).outcome == (
            TextEmbeddingJobOutcome.SUCCESS
        )
        db.refresh(item)
        assert item.text_embedding_needs_reindex is False
        update_item(db, item.id, ItemUpdate(price=99.0), u)
        db.refresh(item)
        assert item.text_embedding_needs_reindex is False
        assert item.price == 99.0

    def test_successful_job_clears_pending(self, db):
        u = User(email="re4@ex.com", username="re4", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Job",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
            listing_type=ListingType.sale.value,
        )
        db.add(it)
        db.commit()
        db.refresh(it)
        assert it.text_embedding_needs_reindex is True
        assert (
            generate_text_embedding_for_item(db, it.id, service=TextEmbeddingService(), commit=True).outcome
            == TextEmbeddingJobOutcome.SUCCESS
        )
        db.refresh(it)
        assert it.text_embedding_needs_reindex is False
        assert it.text_embedding_reindex_requested_at is None

    def test_failed_provider_keeps_pending(self, db):
        u = User(email="re5@ex.com", username="re5", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Fail pls",
            status=ItemStatus.available.value,
            is_public=False,
            listing_domain=ListingDomain.item.value,
            listing_type=ListingType.sale.value,
        )
        db.add(it)
        db.commit()
        assert (
            generate_text_embedding_for_item(
                db, it.id, service=TextEmbeddingService(provider=ExplodingProvider()), commit=True
            ).outcome
            == TextEmbeddingJobOutcome.FAILED_PROVIDER
        )
        db.refresh(it)
        assert it.text_embedding_needs_reindex is True

    def test_count_and_sample_helpers(self, db):
        u = User(email="re6@ex.com", username="re6", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        for i in range(3):
            db.add(
                Item(
                    user_id=u.id,
                    title=f"C{i}",
                    status=ItemStatus.available.value,
                    is_public=False,
                    listing_domain=ListingDomain.item.value,
                    listing_type=ListingType.sale.value,
                )
            )
        db.commit()
        n = count_listings_pending_text_embedding_reindex(db)
        assert n >= 3
        sample = sample_listing_ids_pending_text_embedding_reindex(db, limit=2)
        assert len(sample) == 2
