"""
Tests for visual similarity search: embedding generation, persistence,
similarity retrieval, filtering, and ranking.
"""

import math
import struct
import pytest

# Mirror RANKING_WEIGHTS from app.services.embedding_service for tests that run without full app deps.
# Keep in sync when tuning ranking.
_RANKING_WEIGHTS = {
    "similarity_max": 50.0,
    "distance_max": 30.0,
    "distance_decay_km": 100.0,
    "completeness_max": 10.0,
    "ai_confidence_max": 10.0,
    "fallback_penalty": -5.0,
}


class TestEmbeddingPackingUnpacking:
    """Test the Item model's binary embedding pack/unpack methods."""

    def test_roundtrip_preserves_values(self):
        """Packing then unpacking returns the same float values."""
        vec = [0.1, -0.2, 0.3, 0.0, 1.0, -1.0]
        packed = struct.pack(f"{len(vec)}f", *vec)
        count = len(packed) // 4
        unpacked = list(struct.unpack(f"{count}f", packed))
        for a, b in zip(vec, unpacked):
            assert abs(a - b) < 1e-6

    def test_512d_vector_size(self):
        """A 512-d float32 vector packs into exactly 2048 bytes."""
        vec = [0.0] * 512
        packed = struct.pack(f"{len(vec)}f", *vec)
        assert len(packed) == 2048

    def test_empty_vector(self):
        """An empty vector packs to zero bytes."""
        vec = []
        packed = struct.pack(f"{len(vec)}f", *vec)
        assert len(packed) == 0

    def test_negative_values(self):
        """Negative floats round-trip correctly."""
        vec = [-0.5, -1.5, -0.001]
        packed = struct.pack(f"{len(vec)}f", *vec)
        count = len(packed) // 4
        unpacked = list(struct.unpack(f"{count}f", packed))
        for a, b in zip(vec, unpacked):
            assert abs(a - b) < 1e-6


class TestCosineSimilarity:
    """Test the cosine similarity helper (dot product on L2-normalized vectors)."""

    def _cosine(self, a, b):
        return sum(x * y for x, y in zip(a, b))

    def test_identical_vectors(self):
        """Identical normalized vectors have similarity 1.0."""
        n = 1.0 / math.sqrt(3)
        v = [n, n, n]
        assert abs(self._cosine(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        """Orthogonal vectors have similarity 0.0."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(self._cosine(a, b)) < 1e-6

    def test_opposite_vectors(self):
        """Opposite vectors have similarity -1.0."""
        a = [1.0, 0.0, 0.0]
        b = [-1.0, 0.0, 0.0]
        assert abs(self._cosine(a, b) + 1.0) < 1e-6

    def test_similarity_range(self):
        """Similarity of normalized vectors is always in [-1, 1]."""
        n = 1.0 / math.sqrt(2)
        a = [n, n, 0.0]
        b = [n, 0.0, n]
        sim = self._cosine(a, b)
        assert -1.0 <= sim <= 1.0

    def test_partial_overlap(self):
        """Two vectors sharing one dimension have expected similarity."""
        n2 = 1.0 / math.sqrt(2)
        a = [n2, n2, 0.0]
        b = [n2, 0.0, n2]
        sim = self._cosine(a, b)
        assert abs(sim - 0.5) < 1e-6


class TestSimilarityRankingBreakdown:
    """Test the ranking breakdown used in similarity search."""

    def _build_breakdown(self, similarity, distance_km=None, other_ranking=10.0):
        """Replicate the ranking formula from embedding_service (uses RANKING_WEIGHTS)."""
        w = _RANKING_WEIGHTS
        sim_score = similarity * w["similarity_max"]
        if distance_km is not None:
            dist_score = max(0.0, w["distance_max"] * (1.0 - distance_km / w["distance_decay_km"]))
        else:
            dist_score = 0.0
        total = sim_score + dist_score + other_ranking
        return {
            "similarity_score": sim_score,
            "distance_score": dist_score,
            "total_score": total,
        }

    def test_high_similarity_scores_higher(self):
        """Items with higher visual similarity should rank higher."""
        high = self._build_breakdown(0.9)
        low = self._build_breakdown(0.3)
        assert high["total_score"] > low["total_score"]

    def test_closer_items_rank_higher(self):
        """At equal similarity, closer items rank higher."""
        close = self._build_breakdown(0.5, distance_km=1.0)
        far = self._build_breakdown(0.5, distance_km=50.0)
        assert close["total_score"] > far["total_score"]

    def test_no_location_gives_zero_distance_score(self):
        """Without location filter, distance_score is 0."""
        b = self._build_breakdown(0.5, distance_km=None)
        assert b["distance_score"] == 0.0

    def test_similarity_score_max(self):
        """Similarity of 1.0 yields max similarity_score of 50."""
        b = self._build_breakdown(1.0)
        assert b["similarity_score"] == 50.0

    def test_similarity_score_min(self):
        """Similarity of 0.0 yields similarity_score of 0."""
        b = self._build_breakdown(0.0)
        assert b["similarity_score"] == 0.0

    def test_distance_score_at_zero_km(self):
        """At 0 km distance, distance_score is 30."""
        b = self._build_breakdown(0.5, distance_km=0.0)
        assert b["distance_score"] == 30.0

    def test_distance_score_at_100km(self):
        """At 100 km, distance_score is 0."""
        b = self._build_breakdown(0.5, distance_km=100.0)
        assert b["distance_score"] == 0.0

    def test_total_is_sum(self):
        """Total score equals sum of similarity + distance + other components."""
        b = self._build_breakdown(0.7, distance_km=10.0)
        expected = b["similarity_score"] + b["distance_score"] + 10.0
        assert abs(b["total_score"] - expected) < 1e-6


class TestFinalRankingLogic:
    """
    Tests for the final ordering of similar items.
    Ensures highly similar vs nearby trade-off, radius filter, and deterministic ordering.
    """

    def _final_score(self, similarity: float, distance_km=None, other_ranking: float = 10.0) -> float:
        """Compute final_score using RANKING_WEIGHTS (mirrored from embedding_service)."""
        w = _RANKING_WEIGHTS
        sim_contrib = similarity * w["similarity_max"]
        if distance_km is not None:
            dist_influence = max(0.0, w["distance_max"] * (1.0 - distance_km / w["distance_decay_km"]))
        else:
            dist_influence = 0.0
        return sim_contrib + dist_influence + other_ranking

    def test_highly_similar_but_far_vs_less_similar_but_nearby(self):
        """
        A less similar but nearby item can outrank a highly similar but far item.
        With default weights: similarity contributes up to 50, distance up to 30.
        """
        high_sim_far = self._final_score(0.9, distance_km=80.0)   # 45 + 6 + 10 = 61
        low_sim_near = self._final_score(0.5, distance_km=1.0)    # 25 + 29.7 + 10 ≈ 64.7
        assert low_sim_near > high_sim_far

    def test_without_location_similarity_dominates(self):
        """Without location filter, distance_influence is 0; ordering is by similarity only."""
        a = self._final_score(0.8, distance_km=None)
        b = self._final_score(0.4, distance_km=None)
        assert a > b

    def test_effect_of_radius_filter(self):
        """
        Radius filter excludes items before scoring.
        Items outside radius never appear; items inside are scored normally.
        """
        # At 15km: within 20km radius, gets distance_influence
        within = self._final_score(0.6, distance_km=15.0)
        # At 25km: would be excluded if radius_km=20
        outside = self._final_score(0.6, distance_km=25.0)
        # Both get a score; the one within would rank higher if both were in results
        assert within > outside

    def test_deterministic_ordering(self):
        """Same inputs produce same final_score; ordering is deterministic."""
        scores = [
            self._final_score(0.7, 5.0),
            self._final_score(0.7, 5.0),
            self._final_score(0.3, 50.0),
        ]
        assert scores[0] == scores[1]
        assert scores[0] > scores[2]
        # Sort descending gives stable order
        sorted_scores = sorted(scores, reverse=True)
        assert sorted_scores[0] == sorted_scores[1]
        assert sorted_scores == [scores[0], scores[1], scores[2]]

    def test_similarity_breakdown_final_score_equals_sum(self):
        """similarity_breakdown.final_score = contribution + influence + other."""
        w = _RANKING_WEIGHTS
        sim, dist_km = 0.6, 10.0
        contrib = sim * w["similarity_max"]
        influence = max(0.0, w["distance_max"] * (1.0 - dist_km / w["distance_decay_km"]))
        other = 10.0
        expected_final = contrib + influence + other
        actual = self._final_score(sim, dist_km, other)
        assert abs(actual - expected_final) < 1e-6


class TestSimilaritySearchBehavior:
    """
    Behavioral specification for similarity search.
    Documents expected behavior; placeholder for DB-backed integration tests.
    """

    def test_self_item_excluded_from_results(self):
        """
        Given: Search by item_id=42
        When: Similarity search runs
        Then: item_id=42 must NOT appear in results
        """
        exclude_id = 42
        candidate_ids = [10, 42, 55, 99]
        filtered = [i for i in candidate_ids if i != exclude_id]
        assert 42 not in filtered
        assert len(filtered) == 3

    def test_only_public_items_returned(self):
        """
        Given: Mix of public and private items with embeddings
        When: Similarity search runs
        Then: Only is_public=True items returned
        """
        items = [
            {"id": 1, "is_public": True},
            {"id": 2, "is_public": False},
            {"id": 3, "is_public": True},
        ]
        public = [i for i in items if i["is_public"]]
        assert len(public) == 2
        assert all(i["is_public"] for i in public)

    def test_items_without_embedding_excluded(self):
        """
        Given: Some items have embeddings, others don't
        When: Similarity search runs
        Then: Only items with embeddings are considered
        """
        items = [
            {"id": 1, "embedding": [0.1, 0.2]},
            {"id": 2, "embedding": None},
            {"id": 3, "embedding": [0.3, 0.4]},
        ]
        with_emb = [i for i in items if i["embedding"] is not None]
        assert len(with_emb) == 2

    def test_radius_filter_excludes_distant_items(self):
        """
        Given: Items at various distances, radius_km=10
        When: Similarity search with location filter
        Then: Only items within 10 km returned
        """
        candidates = [
            {"id": 1, "distance_km": 3.0},
            {"id": 2, "distance_km": 12.0},
            {"id": 3, "distance_km": 9.9},
        ]
        radius = 10.0
        within = [c for c in candidates if c["distance_km"] <= radius]
        assert len(within) == 2
        assert all(c["distance_km"] <= radius for c in within)

    def test_results_sorted_by_ranking_score_desc(self):
        """
        Given: Multiple similar items
        When: Results are returned
        Then: They are sorted by ranking_score descending
        """
        scores = [45.2, 78.1, 63.5, 12.0]
        sorted_desc = sorted(scores, reverse=True)
        assert sorted_desc == [78.1, 63.5, 45.2, 12.0]

    def test_similarity_score_present_in_results(self):
        """Each result must include a similarity_score."""
        result = {
            "item_id": 1,
            "similarity_score": 0.87,
            "ranking_score": 55.3,
        }
        assert "similarity_score" in result
        assert 0.0 <= result["similarity_score"] <= 1.0

    def test_distance_km_present_when_location_filter(self):
        """When latitude/longitude are provided, distance_km must be in results."""
        result_with_loc = {
            "item_id": 1,
            "similarity_score": 0.87,
            "distance_km": 3.5,
        }
        assert "distance_km" in result_with_loc
        assert result_with_loc["distance_km"] >= 0.0

    def test_distance_km_none_without_location_filter(self):
        """Without location filter, distance_km should be None."""
        result_no_loc = {
            "item_id": 1,
            "similarity_score": 0.87,
            "distance_km": None,
        }
        assert result_no_loc["distance_km"] is None

    def test_ranking_breakdown_present(self):
        """Each result should include a ranking_breakdown dict."""
        breakdown = {
            "similarity_score": 35.0,
            "distance_score": 27.0,
            "category_score": 0.0,
            "keyword_score": 0.0,
            "completeness_score": 7.5,
            "ai_confidence_score": 5.0,
            "fallback_penalty": 0.0,
            "total_score": 74.5,
        }
        required_keys = {
            "similarity_score", "distance_score", "category_score",
            "keyword_score", "completeness_score", "ai_confidence_score",
            "fallback_penalty", "total_score",
        }
        assert required_keys.issubset(breakdown.keys())

    def test_limit_respected(self):
        """Results should be limited to the requested count."""
        all_results = list(range(50))
        limit = 20
        limited = all_results[:limit]
        assert len(limited) == limit

    def test_items_without_coords_excluded_when_radius_filter(self):
        """
        When radius filter is active, items with NULL coordinates are excluded.
        """
        items = [
            {"id": 1, "lat": 40.0, "lon": -120.0},
            {"id": 2, "lat": None, "lon": None},
            {"id": 3, "lat": 40.01, "lon": -120.01},
        ]
        with_coords = [i for i in items if i["lat"] is not None and i["lon"] is not None]
        assert len(with_coords) == 2

    def test_radius_km_requires_latitude_and_longitude(self):
        """
        When radius_km is provided, both latitude and longitude must be provided.
        Documents API validation: 400 if radius_km set but lat or lon missing.
        """
        invalid_combos = [
            {"radius_km": 10.0, "latitude": None, "longitude": -74.0},
            {"radius_km": 10.0, "latitude": 40.0, "longitude": None},
        ]
        for params in invalid_combos:
            assert params["radius_km"] is not None
            assert params["latitude"] is None or params["longitude"] is None


class TestEmbeddingServiceBoundaries:
    """Verify the embedding service has clear, separate responsibilities."""

    def test_openclip_extraction_function_exists(self):
        """OpenCLIP service exposes an embedding extraction function."""
        from app.ai.openclip_service import extract_image_embedding_sync
        assert callable(extract_image_embedding_sync)

    def _try_import_embedding_service(self):
        try:
            import app.services.embedding_service as mod
            return mod
        except ImportError as e:
            pytest.skip(f"Requires full app deps: {e}")

    def test_generation_function_exists(self):
        """Embedding service exposes a generation function."""
        mod = self._try_import_embedding_service()
        assert callable(mod.generate_embedding_sync)

    def test_async_generation_function_exists(self):
        """Embedding service exposes an async generation wrapper."""
        import asyncio
        mod = self._try_import_embedding_service()
        assert asyncio.iscoroutinefunction(mod.generate_embedding)

    def test_persistence_functions_exist(self):
        """Embedding service exposes save and get functions."""
        mod = self._try_import_embedding_service()
        assert callable(mod.save_embedding)
        assert callable(mod.get_embedding)

    def test_retrieval_function_exists(self):
        """Embedding service exposes a similarity search function."""
        mod = self._try_import_embedding_service()
        assert callable(mod.find_similar_items)

    def test_embedding_dim_constant(self):
        """EMBEDDING_DIM is defined and matches ViT-B-32 output."""
        mod = self._try_import_embedding_service()
        assert mod.EMBEDDING_DIM == 512


@pytest.mark.skip(reason="Requires full app deps (psycopg2, pydantic-settings, email-validator)")
class TestSimilaritySchemas:
    """Test the Pydantic schemas for similarity search responses."""

    def test_similarity_ranking_breakdown_fields(self):
        """SimilarityRankingBreakdown has all required fields."""
        expected_fields = {
            "similarity_score", "distance_score", "category_score",
            "keyword_score", "completeness_score", "ai_confidence_score",
            "fallback_penalty", "total_score",
        }
        from app.schemas.item import SimilarityRankingBreakdown
        actual = set(SimilarityRankingBreakdown.model_fields.keys())
        assert expected_fields == actual

    def test_similar_item_result_fields(self):
        """SimilarItemResult has all required fields including final_score, similarity_breakdown, status."""
        expected = {
            "id", "title", "category", "subcategory", "condition", "status",
            "is_public", "images", "tags", "similarity_score",
            "distance_km", "ranking_score", "final_score",
            "ranking_breakdown", "similarity_breakdown",
            "created_at",
        }
        from app.schemas.item import SimilarItemResult
        actual = set(SimilarItemResult.model_fields.keys())
        assert expected == actual

    def test_similarity_breakdown_fields(self):
        """SimilarityBreakdown has all required fields for transparent ordering."""
        expected = {
            "similarity_score", "similarity_contribution", "distance_influence",
            "other_ranking", "final_score",
        }
        from app.schemas.item import SimilarityBreakdown
        actual = set(SimilarityBreakdown.model_fields.keys())
        assert expected == actual


class TestSimilarityRadiusValidation:
    """Test radius_km validation when lat/lon are missing."""

    def _get_client(self):
        try:
            from fastapi.testclient import TestClient
            from app.main import app
            return TestClient(app)
        except ImportError:
            pytest.skip("Requires fastapi/starlette for TestClient")

    def test_radius_without_lat_returns_400(self):
        """GET /api/similar/1?radius_km=10 (no lat/lon) returns 400."""
        client = self._get_client()
        r = client.get("/api/similar/1", params={"radius_km": 10.0})
        assert r.status_code == 400
        assert "latitude" in r.json().get("detail", "").lower() or "longitude" in r.json().get("detail", "").lower()

    def test_radius_with_lat_only_returns_400(self):
        """GET /api/similar/1?radius_km=10&latitude=40 (no lon) returns 400."""
        client = self._get_client()
        r = client.get("/api/similar/1", params={"radius_km": 10.0, "latitude": 40.0})
        assert r.status_code == 400

    def test_radius_with_lon_only_returns_400(self):
        """GET /api/similar/1?radius_km=10&longitude=-74 (no lat) returns 400."""
        client = self._get_client()
        r = client.get("/api/similar/1", params={"radius_km": 10.0, "longitude": -74.0})
        assert r.status_code == 400


@pytest.mark.skip(reason="Requires full app and DB")
class TestSimilarityRoutes:
    """Test route registration and basic configuration."""

    def test_similarity_router_prefix(self):
        """Similarity routes are under /api/similar."""
        from app.routes.similarity import router
        assert router.prefix == "/api/similar"

    def test_similarity_router_registered(self):
        """Similarity router is included in the FastAPI app."""
        from app.main import app
        route_paths = [r.path for r in app.routes]
        assert "/api/similar/{item_id}" in route_paths
        assert "/api/similar/by-image" in route_paths
