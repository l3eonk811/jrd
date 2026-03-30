"""
Hybrid lexical + text-vector ranking for discover search (Phase 2).

Lexical signal is a normalized approximation of keyword overlap (title-first).
Vector signal is cosine similarity on Phase 1 text embeddings with the freshness gate.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

from app.config import Settings, get_settings
from app.domain.text_embedding_errors import EmptySemanticTextInputError, InvalidTextEmbeddingVectorError
from app.models.item import Item
from app.services.query_embedding_service import QueryEmbeddingService
from app.services.semantic_text import normalize_free_text_for_embedding_query
from app.services.text_vector_search_service import TextVectorSearchService

logger = logging.getLogger(__name__)

# Lexical raw scale upper bound (matches max sum from title+cat+tags+service+animal+desc)
_KEYWORD_RAW_MAX = 56.0


def _keyword_score_raw(item: Item, q_lower: str) -> float:
    """Same field coverage as ``item_service._calculate_ranking_score`` keyword block (0..~56)."""
    score = 0.0
    title_lower = (item.title or "").lower()
    desc_lower = (item.description or "").lower()
    cat_lower = (item.category or "").lower()
    subcat_lower = (item.subcategory or "").lower()
    tag_names = [it.tag.name.lower() for it in (item.item_tags or []) if it.tag]
    service_cat = (
        item.service_details.service_category.lower()
        if item.service_details and item.service_details.service_category
        else ""
    )
    animal_type = (
        item.adoption_details.animal_type.lower()
        if item.adoption_details and item.adoption_details.animal_type
        else ""
    )
    if q_lower in title_lower:
        score += 15.0
    if q_lower in cat_lower or q_lower in subcat_lower:
        score += 10.0
    if any(q_lower in t for t in tag_names):
        score += 10.0
    if service_cat and q_lower in service_cat:
        score += 8.0
    if animal_type and q_lower in animal_type:
        score += 8.0
    if q_lower in desc_lower:
        score += 5.0
    return score


def normalized_lexical_relevance(item: Item, query_normalized: str) -> float:
    """
    Lexical relevance in [0, 1]. Exact normalized title match (casefold) => 1.0 so
    high-precision hits are not buried by weak vectors (floor applied separately).
    """
    if not query_normalized:
        return 0.0
    q = query_normalized.casefold()
    title_n = normalize_free_text_for_embedding_query(item.title or "")
    tl = title_n.casefold()
    if tl == q:
        return 1.0
    if tl.startswith(q) and len(q) >= 2:
        return 0.95
    if q in tl:
        return 0.88
    raw = _keyword_score_raw(item, q)
    if raw <= 0.0:
        return 0.0
    return min(1.0, raw / _KEYWORD_RAW_MAX)


def _normalize_hybrid_weights(settings: Settings) -> Tuple[float, float]:
    a = max(0.0, float(settings.search_hybrid_lexical_weight))
    b = max(0.0, float(settings.search_hybrid_vector_weight))
    s = a + b
    if s <= 0.0:
        return 0.5, 0.5
    return a / s, b / s


def compute_hybrid_score(lexical_01: float, cosine: float, *, settings: Settings) -> float:
    """
    Hybrid score in [0, 1].

    ``cosine`` in [-1, 1] is mapped to [0, 1] via (cosine + 1) / 2.
    Exact title (lexical_01 == 1.0) applies ``search_hybrid_exact_title_floor`` minimum.
    """
    vec_01 = (float(cosine) + 1.0) / 2.0
    w_lex, w_vec = _normalize_hybrid_weights(settings)
    combined = w_lex * lexical_01 + w_vec * vec_01
    if lexical_01 >= 1.0 - 1e-12:
        combined = max(combined, float(settings.search_hybrid_exact_title_floor))
    return min(1.0, max(0.0, combined))


def maybe_apply_text_vector_ranking(
    results: List[dict[str, Any]],
    *,
    raw_query: Optional[str],
    text_search_mode: Optional[str],
    sort: Optional[str],
    settings: Optional[Settings] = None,
    query_svc: Optional[QueryEmbeddingService] = None,
    vector_svc: Optional[TextVectorSearchService] = None,
) -> None:
    """
    Mutates ``results`` in place: reorders and updates scores/breakdowns when vector path runs.

    No-op for lexical-only, disabled flag, empty query, or sorts that are not relevance-based.
    On failure, sets ``text_search_fallback_reason`` on each row's ranking_breakdown and keeps order.
    """
    st = settings or get_settings()
    mode = (text_search_mode or "lexical").lower().strip()
    if mode not in ("hybrid", "semantic"):
        return
    if not st.enable_text_vector_search:
        _tag_fallback(results, mode, "text_vector_search_disabled")
        return
    if sort in ("price_asc", "price_desc", "newest", "oldest", "nearest"):
        _tag_fallback(results, mode, f"sort_{sort}_lexical_only")
        return

    nq = normalize_free_text_for_embedding_query(raw_query or "")
    if not nq:
        _tag_fallback(results, mode, "empty_query_no_vector_ranking")
        return

    cap = max(1, int(st.search_vector_candidate_cap))
    if len(results) > cap:
        logger.warning(
            "text_vector_rerank defensive cap: input_len=%s search_vector_candidate_cap=%s (truncating by item.id)",
            len(results),
            cap,
        )
        results.sort(key=lambda r: r["item"].id)
        results[:] = results[:cap]

    q_svc = query_svc or QueryEmbeddingService()
    v_svc = vector_svc or TextVectorSearchService()
    try:
        qvec = q_svc.embed_query_vector(raw_query or "")
    except (EmptySemanticTextInputError, InvalidTextEmbeddingVectorError) as e:
        logger.warning("query embedding failed: %s", e)
        _tag_fallback(results, mode, f"query_embedding_failed:{type(e).__name__}")
        return

    items = [r["item"] for r in results]
    cos_map = v_svc.score_items_by_text_similarity(items, qvec)

    for r in results:
        item: Item = r["item"]
        bd = r["ranking_breakdown"]
        cos = cos_map.get(item.id)
        lex = normalized_lexical_relevance(item, nq)

        bd["text_vector_cosine"] = round(float(cos), 6) if cos is not None else None
        bd["text_lexical_norm"] = round(float(lex), 4)
        bd["text_search_mode_applied"] = mode

        if mode == "semantic":
            if cos is None:
                bd["text_hybrid_score"] = None
                bd["text_semantic_rank_score"] = None
                continue
            vec_01 = (float(cos) + 1.0) / 2.0
            bd["text_hybrid_score"] = round(vec_01, 4)
            bd["text_semantic_rank_score"] = round(vec_01, 4)
        else:
            if cos is None:
                bd["text_hybrid_score"] = round(float(lex), 4)
            else:
                h = compute_hybrid_score(lex, float(cos), settings=st)
                bd["text_hybrid_score"] = round(h, 4)

    if mode == "semantic":
        results[:] = [r for r in results if r["ranking_breakdown"].get("text_vector_cosine") is not None]
        results.sort(
            key=lambda x: (
                -(x["ranking_breakdown"].get("text_semantic_rank_score") or 0.0),
                x.get("distance_km") if x.get("distance_km") is not None else 1e9,
                x["item"].id,
            )
        )
        for r in results:
            ts = r["ranking_breakdown"].get("text_semantic_rank_score")
            r["ranking_score"] = round(100.0 * float(ts), 4)
            r["ranking_reason"] = f"semantic_text_vector_cos={r['ranking_breakdown'].get('text_vector_cosine')}"
    else:
        results.sort(
            key=lambda x: (
                -(x["ranking_breakdown"].get("text_hybrid_score") or 0.0),
                x.get("distance_km") if x.get("distance_km") is not None else 1e9,
                x["item"].id,
            )
        )
        for r in results:
            h = r["ranking_breakdown"].get("text_hybrid_score")
            if h is not None:
                r["ranking_score"] = round(100.0 * float(h), 4)
                r["ranking_reason"] = (
                    f"hybrid_lex={r['ranking_breakdown'].get('text_lexical_norm')} "
                    f"cos={r['ranking_breakdown'].get('text_vector_cosine')}"
                )


def _tag_fallback(results: List[dict[str, Any]], requested_mode: str, reason: str) -> None:
    for r in results:
        r["ranking_breakdown"]["text_search_fallback_reason"] = reason
        r["ranking_breakdown"]["text_search_mode_applied"] = requested_mode
