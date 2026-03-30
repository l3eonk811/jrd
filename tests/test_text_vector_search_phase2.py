"""
Phase 2: query embedding, cosine similarity, vector/hybrid search, item_service integration.
"""

from __future__ import annotations

import math
import pathlib
import sys
from datetime import datetime, timezone
from typing import List

import pytest
from sqlalchemy import update

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.config import Settings
from app.domain.text_embedding_constants import TEXT_EMBEDDING_DIM
from app.domain.text_embedding_errors import EmptySemanticTextInputError, InvalidTextEmbeddingVectorError
from app.domain.text_embedding_similarity import cosine_similarity
from app.models.item import Item, ItemStatus, ListingDomain
from app.models.user import User
from app.services.hybrid_search_service import (
    compute_hybrid_score,
    maybe_apply_text_vector_ranking,
    normalized_lexical_relevance,
)
from app.services.semantic_text import (
    build_semantic_text,
    compute_embedding_source_fingerprint,
    normalize_free_text_for_embedding_query,
)
from app.services.item_service import search_nearby_items
from app.services.query_embedding_service import QueryEmbeddingService
from app.services.text_embedding_providers import TextEmbeddingProvider
from app.services.text_embedding_service import generate_text_embedding_for_item, validate_provider_embedding_vector
from app.services.text_vector_search_service import TextVectorSearchService


def _valid_unit(seed: float = 0.02) -> List[float]:
    v = [seed] * TEXT_EMBEDDING_DIM
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _axis_unit(dim_index: int) -> List[float]:
    v = [0.0] * TEXT_EMBEDDING_DIM
    v[dim_index] = 1.0
    return v


def _persist_manual_text_embedding(db, item: Item, vector: List[float]) -> None:
    db.refresh(item)
    sem = build_semantic_text(item)
    item.semantic_text = sem
    item.set_text_embedding(vector)
    item.text_embedding_source_hash = compute_embedding_source_fingerprint(sem)
    item.text_embedding_updated_at = datetime.now(timezone.utc)
    db.commit()


class FixedQueryVecProvider(TextEmbeddingProvider):
    """Returns a fixed L2 unit vector for every query (tests only)."""

    def __init__(self, vec: List[float]) -> None:
        self._vec = list(vec)

    def embed(self, text: str) -> List[float]:
        return list(self._vec)


class TestCosineSimilarity:
    def test_identical_unit_vectors(self):
        a = _valid_unit(0.03)
        assert abs(cosine_similarity(a, a) - 1.0) < 1e-5

    def test_orthogonal_pair(self):
        a = [0.0] * TEXT_EMBEDDING_DIM
        b = [0.0] * TEXT_EMBEDDING_DIM
        a[0] = 1.0
        b[1] = 1.0
        assert abs(cosine_similarity(a, b)) < 1e-9

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="mismatch"):
            cosine_similarity([0.0, 1.0], [0.0])

    def test_deterministic_ordering(self):
        a = _valid_unit(0.1)
        b = _valid_unit(0.2)
        s1 = cosine_similarity(a, b)
        s2 = cosine_similarity(a, b)
        assert s1 == s2


class TestQueryEmbeddingService:
    def test_empty_raises(self):
        with pytest.raises(EmptySemanticTextInputError):
            QueryEmbeddingService().embed_query_vector("")
        with pytest.raises(EmptySemanticTextInputError):
            QueryEmbeddingService().embed_query_vector("   \n")

    def test_valid_length_and_finite(self):
        v = QueryEmbeddingService().embed_query_vector("hello query")
        validate_provider_embedding_vector(v)
        assert len(v) == TEXT_EMBEDDING_DIM

    def test_bad_provider_rejected(self):
        class Bad(TextEmbeddingProvider):
            dim = TEXT_EMBEDDING_DIM

            def embed(self, text: str) -> List[float]:
                return [0.0] * 5

        with pytest.raises(InvalidTextEmbeddingVectorError):
            QueryEmbeddingService(provider=Bad()).embed_query_vector("x")


class TestLexicalAndHybridFormula:
    def test_exact_title_is_one(self):
        it = Item(title="  Hello  ")
        assert normalized_lexical_relevance(it, "Hello") == 1.0

    def test_hybrid_exact_title_floor(self):
        s = Settings()
        # terrible vector: cosine -1 -> vec_01 = 0
        h = compute_hybrid_score(1.0, -1.0, settings=s)
        assert h >= s.search_hybrid_exact_title_floor


class TestTextVectorSearchServiceStale:
    def test_bulk_update_excludes_from_scores(self, db):
        u = User(email="tv2@ex.com", username="tv2", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        it = Item(
            user_id=u.id,
            title="Stale vec",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=24.71,
            longitude=46.61,
        )
        db.add(it)
        db.commit()
        generate_text_embedding_for_item(db, it.id, commit=True)
        db.refresh(it)
        qv = QueryEmbeddingService().embed_query_vector("Stale vec")
        svc = TextVectorSearchService()
        assert it.id in svc.score_items_by_text_similarity([it], qv)
        db.execute(update(Item).where(Item.id == it.id).values(title="Changed bulk"))
        db.commit()
        db.refresh(it)
        assert it.id not in svc.score_items_by_text_similarity([it], qv)


class TestHybridRerankBreakdown:
    def test_hybrid_populates_breakdown(self):
        from app.models.item import Item as ItemCls

        a = ItemCls(id=2, title="Alpha tool", latitude=1.0, longitude=1.0)
        b = ItemCls(id=1, title="Beta tool", latitude=1.0, longitude=1.0)
        results = []
        for it in (a, b):
            results.append(
                {
                    "item": it,
                    "distance_km": 1.0,
                    "ranking_score": 50.0,
                    "ranking_reason": "x",
                    "ranking_breakdown": {
                        "distance_score": 10.0,
                        "category_score": 0.0,
                        "keyword_score": 5.0,
                        "completeness_score": 0.0,
                        "ai_confidence_score": 0.0,
                        "fallback_penalty": 0.0,
                        "total_score": 15.0,
                    },
                }
            )
        maybe_apply_text_vector_ranking(
            results,
            raw_query="tool",
            text_search_mode="hybrid",
            sort=None,
            query_svc=QueryEmbeddingService(),
            vector_svc=TextVectorSearchService(),
        )
        for r in results:
            assert r["ranking_breakdown"].get("text_hybrid_score") is not None
            assert r["ranking_breakdown"].get("text_search_mode_applied") == "hybrid"


class TestSearchNearbyHybridIntegration:
    def test_hybrid_prefers_lexical_bicycle_match(self, db):
        u = User(
            email="hyb@ex.com",
            username="hyb_u",
            hashed_password="x",
            latitude=24.7,
            longitude=46.6,
        )
        db.add(u)
        db.flush()
        lat, lon = 24.7136, 46.6753
        a = Item(
            user_id=u.id,
            title="Red bicycle for sale",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=lat,
            longitude=lon,
        )
        b = Item(
            user_id=u.id,
            title="Garden hose green",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=lat,
            longitude=lon,
        )
        db.add_all([a, b])
        db.commit()
        generate_text_embedding_for_item(db, a.id, commit=True)
        generate_text_embedding_for_item(db, b.id, commit=True)

        rows, total = search_nearby_items(
            db,
            latitude=lat,
            longitude=lon,
            radius_km=5.0,
            query="bicycle",
            text_search_mode="hybrid",
            page=1,
            page_size=10,
        )
        assert total >= 1
        assert rows[0]["item"].title.startswith("Red bicycle")

    def test_lexical_default_unchanged_no_mode(self, db):
        u = User(email="lex@ex.com", username="lex_u", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        lat, lon = 24.7136, 46.6753
        far = Item(
            user_id=u.id,
            title="Near",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=lat,
            longitude=lon,
        )
        near = Item(
            user_id=u.id,
            title="Far item",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=lat + 0.05,
            longitude=lon + 0.05,
        )
        db.add_all([far, near])
        db.commit()
        rows, _ = search_nearby_items(
            db,
            latitude=lat,
            longitude=lon,
            radius_km=50.0,
            query=None,
            page=1,
            page_size=10,
        )
        assert rows[0]["item"].title == "Near"

    def test_semantic_drops_items_without_embedding(self, db):
        u = User(email="sem@ex.com", username="sem_u", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        lat, lon = 24.7136, 46.6753
        with_emb = Item(
            user_id=u.id,
            title="Indexed only",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=lat,
            longitude=lon,
        )
        no_emb = Item(
            user_id=u.id,
            title="No embedding row",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=lat,
            longitude=lon,
        )
        db.add_all([with_emb, no_emb])
        db.commit()
        generate_text_embedding_for_item(db, with_emb.id, commit=True)

        rows, total = search_nearby_items(
            db,
            latitude=lat,
            longitude=lon,
            radius_km=5.0,
            query="Indexed",
            text_search_mode="semantic",
            page=1,
            page_size=10,
        )
        assert all(r["item"].id == with_emb.id for r in rows)
        assert total == 1


class TestHybridRankingAcceptance:
    """
    Closure: strong lexical + weak vector must not rank below weak lexical + strong vector
    when exact-title floor applies (documented hybrid formula).
    """

    def test_exact_title_match_not_buried_by_better_vector_weaker_lexical(self, db, monkeypatch):
        q_vec = _axis_unit(0)
        fixed_q = QueryEmbeddingService(provider=FixedQueryVecProvider(q_vec))
        monkeypatch.setattr(
            "app.services.hybrid_search_service.QueryEmbeddingService",
            lambda *a, **kw: fixed_q,
        )

        vec_a = _axis_unit(1)
        vec_b = _axis_unit(0)
        settings = Settings()
        h_a = compute_hybrid_score(1.0, cosine_similarity(q_vec, vec_a), settings=settings)
        h_b = compute_hybrid_score(0.0, cosine_similarity(q_vec, vec_b), settings=settings)
        assert h_a >= settings.search_hybrid_exact_title_floor
        assert h_b < h_a

        u = User(email="acc@ex.com", username="acc_u", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        lat, lon = 24.7136, 46.6753
        item_a = Item(
            user_id=u.id,
            title="Gizmo Pro X",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=lat,
            longitude=lon,
        )
        item_b = Item(
            user_id=u.id,
            title="Unrelated noise listing",
            description="Gizmo Pro X compatible accessory kit",
            status=ItemStatus.available.value,
            is_public=True,
            listing_domain=ListingDomain.item.value,
            latitude=lat,
            longitude=lon,
        )
        db.add_all([item_a, item_b])
        db.commit()
        db.refresh(item_a)
        db.refresh(item_b)
        _persist_manual_text_embedding(db, item_a, vec_a)
        _persist_manual_text_embedding(db, item_b, vec_b)

        qtext = "Gizmo Pro X"
        db.refresh(item_b)
        assert normalized_lexical_relevance(item_a, normalize_free_text_for_embedding_query(qtext)) == 1.0
        lex_b = normalized_lexical_relevance(item_b, normalize_free_text_for_embedding_query(qtext))
        assert lex_b < 0.2
        h_b_pre = compute_hybrid_score(lex_b, cosine_similarity(q_vec, vec_b), settings=settings)
        assert h_b_pre < h_a

        rows, total = search_nearby_items(
            db,
            latitude=lat,
            longitude=lon,
            radius_km=5.0,
            query=qtext,
            text_search_mode="hybrid",
            page=1,
            page_size=10,
        )
        assert total == 2
        assert rows[0]["item"].id == item_a.id
        assert rows[0]["ranking_breakdown"]["text_lexical_norm"] == 1.0
        assert rows[0]["ranking_breakdown"]["text_vector_cosine"] is not None
        assert rows[1]["item"].id == item_b.id


class TestVectorCandidateCapEnforced:
    """Closure: vector rerank work is bounded by search_vector_candidate_cap."""

    def test_search_nearby_truncates_pairs_before_hybrid_rerank(self, db, monkeypatch):
        base = Settings()

        def _gs():
            return base.model_copy(update={"search_vector_candidate_cap": 2})

        monkeypatch.setattr("app.services.item_service.get_settings", _gs)

        u = User(email="cap@ex.com", username="cap_u", hashed_password="x", latitude=24.7, longitude=46.6)
        db.add(u)
        db.flush()
        lat, lon = 24.7136, 46.6753
        items = []
        for t in ("captest aaa", "captest bbb", "captest ccc"):
            it = Item(
                user_id=u.id,
                title=t,
                status=ItemStatus.available.value,
                is_public=True,
                listing_domain=ListingDomain.item.value,
                latitude=lat,
                longitude=lon,
            )
            db.add(it)
            items.append(it)
        db.commit()
        for it in items:
            generate_text_embedding_for_item(db, it.id, commit=True)

        rows, total = search_nearby_items(
            db,
            latitude=lat,
            longitude=lon,
            radius_km=5.0,
            query="captest",
            text_search_mode="hybrid",
            page=1,
            page_size=10,
        )
        assert total == 2
        returned_ids = {r["item"].id for r in rows}
        all_ids = sorted(it.id for it in items)
        assert returned_ids == set(all_ids[:2])

    def test_maybe_apply_defensive_cap_truncates_oversized_batch(self, monkeypatch):
        st = Settings().model_copy(update={"search_vector_candidate_cap": 3})
        q_vec = _axis_unit(0)
        fixed_q = QueryEmbeddingService(provider=FixedQueryVecProvider(q_vec))
        monkeypatch.setattr(
            "app.services.hybrid_search_service.QueryEmbeddingService",
            lambda *a, **kw: fixed_q,
        )
        results = []
        for i in range(5):
            it = Item(id=9000 + i, title=f"Z{i}", latitude=1.0, longitude=1.0)
            results.append(
                {
                    "item": it,
                    "distance_km": 1.0,
                    "ranking_score": 10.0,
                    "ranking_reason": "x",
                    "ranking_breakdown": {
                        "distance_score": 1.0,
                        "category_score": 0.0,
                        "keyword_score": 0.0,
                        "completeness_score": 0.0,
                        "ai_confidence_score": 0.0,
                        "fallback_penalty": 0.0,
                        "total_score": 1.0,
                    },
                }
            )
        maybe_apply_text_vector_ranking(
            results,
            raw_query="Z",
            text_search_mode="hybrid",
            sort=None,
            settings=st,
            vector_svc=TextVectorSearchService(),
        )
        assert len(results) == 3
        assert [r["item"].id for r in results] == [9000, 9001, 9002]
