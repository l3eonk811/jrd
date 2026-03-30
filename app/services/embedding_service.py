"""
Embedding Service — generate, persist, retrieve, and compare image embeddings.

Boundaries:
  - Generation:   delegates to OpenCLIP for image → 512-d vector
  - Persistence:  stores/loads packed float32 binary on the Item model
  - Retrieval:    loads all public-item embeddings for brute-force comparison
  - Comparison:   cosine similarity (dot product on L2-normalized vectors)

MVP uses packed float32 binary blobs on the Item model (no extensions required).
Upgrade path: replace find_similar_items() with pgvector ORDER BY embedding <=> query
or a dedicated vector DB; generation and persistence interfaces stay the same.
"""

import asyncio
import logging
import math
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models.item import Item, DISCOVERABLE_STATUSES
from app.utils.geo import haversine_km

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 512

# ── Ranking weights (tune here for different ordering behavior) ─────────────────
# Final score = similarity_contribution + distance_influence + other_ranking
# Results are sorted by final_score descending.
RANKING_WEIGHTS = {
    "similarity_max": 50.0,      # similarity * similarity_max → 0–50 pts
    "distance_max": 30.0,       # distance_influence when at 0 km
    "distance_decay_km": 100.0, # distance_influence = max(0, distance_max * (1 - km/decay))
    "completeness_max": 10.0,
    "ai_confidence_max": 10.0,
    "fallback_penalty": -5.0,
}


# ── Generation ────────────────────────────────────────────────────────────────

def generate_embedding_sync(image_path: Path, device: str = "cpu") -> List[float]:
    from app.ai.openclip_service import extract_image_embedding_sync
    return extract_image_embedding_sync(image_path, device=device)


async def generate_embedding(image_path: Path, device: str = "cpu") -> List[float]:
    return await asyncio.to_thread(generate_embedding_sync, image_path, device)


# ── Persistence ───────────────────────────────────────────────────────────────

def save_embedding(db: Session, item_id: int, vector: List[float]) -> None:
    item = db.query(Item).filter(Item.id == item_id).first()
    if item is None:
        raise ValueError(f"Item {item_id} not found")
    item.set_embedding(vector)
    db.commit()


def get_embedding(db: Session, item_id: int) -> Optional[List[float]]:
    item = db.query(Item).filter(Item.id == item_id).first()
    if item is None:
        return None
    return item.get_embedding()


# ── Retrieval / Similarity ────────────────────────────────────────────────────

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Dot-product similarity (vectors are assumed L2-normalized)."""
    return sum(x * y for x, y in zip(a, b))


def find_similar_items(
    db: Session,
    query_vector: List[float],
    *,
    exclude_item_id: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_km: Optional[float] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[dict], int]:
    """
    Brute-force similarity search across all public items with embeddings.

    Ordering (explicit and documented):
      Results are sorted by final_score descending.
      final_score = similarity_contribution + distance_influence + other_ranking
        - similarity_contribution: raw cosine (0–1) * RANKING_WEIGHTS["similarity_max"]
        - distance_influence: 0 when no location filter; else inverse of distance
        - other_ranking: completeness + AI confidence + fallback penalty

    Returns (list of dicts sorted by final_score descending, total_count):
      {
        "item": Item,
        "similarity_score": float,      # raw cosine 0–1
        "distance_km": float | None,
        "ranking_score": float,         # legacy; same as final_score
        "final_score": float,           # explicit sort key
        "ranking_breakdown": {...},
        "similarity_breakdown": {...},
      }
    """
    q = (
        db.query(Item)
        .filter(Item.is_public.is_(True))
        .filter(Item.status.in_(DISCOVERABLE_STATUSES))
        .filter(Item.image_embedding.isnot(None))
        .options(
            joinedload(Item.images),
            joinedload(Item.item_tags),
        )
    )
    if exclude_item_id is not None:
        q = q.filter(Item.id != exclude_item_id)

    # Non-core path: cap brute-force work — among most recently created listings with embeddings
    cap = get_settings().similarity_max_brute_force_items
    candidates = q.order_by(Item.id.desc()).limit(cap).all()
    results: List[dict] = []

    for item in candidates:
        item_vec = item.get_embedding()
        if item_vec is None:
            continue

        distance_km: Optional[float] = None
        if latitude is not None and longitude is not None:
            if item.latitude is None or item.longitude is None:
                continue
            distance_km = haversine_km(latitude, longitude, item.latitude, item.longitude)
            if radius_km is not None and distance_km > radius_km:
                continue

        similarity = _cosine_similarity(query_vector, item_vec)

        breakdown, sim_breakdown = _build_ranking_breakdown(
            similarity=similarity,
            distance_km=distance_km,
            item=item,
        )

        final_score = breakdown["total_score"]

        results.append({
            "item": item,
            "similarity_score": round(similarity, 4),
            "distance_km": round(distance_km, 2) if distance_km is not None else None,
            "ranking_score": round(final_score, 4),
            "final_score": round(final_score, 4),
            "ranking_breakdown": breakdown,
            "similarity_breakdown": sim_breakdown,
        })

    results.sort(key=lambda r: r["final_score"], reverse=True)
    total_count = len(results)
    offset = (page - 1) * page_size
    return results[offset : offset + page_size], total_count


def _build_ranking_breakdown(
    *,
    similarity: float,
    distance_km: Optional[float],
    item: Item,
) -> Tuple[dict, dict]:
    """
    Build ranking breakdown and similarity_breakdown.

    Uses RANKING_WEIGHTS for tunable scoring. Returns:
      - ranking_breakdown: full component breakdown (legacy + detail)
      - similarity_breakdown: explicit final ordering components
    """
    w = RANKING_WEIGHTS

    similarity_contribution = similarity * w["similarity_max"]

    if distance_km is not None:
        distance_influence = max(
            0.0,
            w["distance_max"] * (1.0 - distance_km / w["distance_decay_km"]),
        )
    else:
        distance_influence = 0.0

    has_images = bool(item.images)
    has_desc = bool(item.description)
    has_tags = bool(item.item_tags)
    has_coords = item.latitude is not None and item.longitude is not None
    completeness = sum([has_images, has_desc, has_tags, has_coords]) / 4.0
    completeness_score = completeness * w["completeness_max"]

    ai_conf = 0.0
    latest = item.latest_ai_analysis if hasattr(item, "latest_ai_analysis") else None
    if latest and latest.confidence:
        ai_conf = latest.confidence
    ai_confidence_score = ai_conf * w["ai_confidence_max"]

    fallback_penalty = w["fallback_penalty"] if (latest and latest.used_fallback) else 0.0

    other_ranking = completeness_score + ai_confidence_score + fallback_penalty
    final_score = similarity_contribution + distance_influence + other_ranking

    ranking_breakdown = {
        "similarity_score": round(similarity_contribution, 4),
        "distance_score": round(distance_influence, 4),
        "category_score": 0.0,
        "keyword_score": 0.0,
        "completeness_score": round(completeness_score, 4),
        "ai_confidence_score": round(ai_confidence_score, 4),
        "fallback_penalty": round(fallback_penalty, 4),
        "total_score": round(final_score, 4),
    }

    similarity_breakdown = {
        "similarity_score": round(similarity, 4),
        "similarity_contribution": round(similarity_contribution, 4),
        "distance_influence": round(distance_influence, 4),
        "other_ranking": round(other_ranking, 4),
        "final_score": round(final_score, 4),
    }

    return ranking_breakdown, similarity_breakdown
