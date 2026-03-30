# Text vector search (Phase 2)

Phase 2 adds **optional** hybrid and semantic ranking on top of the existing discover search API. Phase 1 guarantees (`TEXT_EMBEDDING_DIM`-sized packed `text_embedding`, fingerprint gate `listing_has_current_text_embedding`, indexing CLI) are unchanged.

## Activation

- Query parameter: `text_search_mode` on `GET /api/search` and `GET /api/search/bounds`.
- Values: omit or `lexical` (default), `hybrid`, `semantic`.
- Config: `enable_text_vector_search` (default true). When false, hybrid/semantic requests **do not** re-rank; `ranking_breakdown.text_search_fallback_reason` explains the skip.

## Query embedding lifecycle

1. Raw `query` → `normalize_free_text_for_embedding_query` (NFC, trim, collapse internal whitespace — same fragment rules as semantic field normalization; not full `build_semantic_text`).
2. Empty/whitespace after normalization → no vector request; fallback tagging (`empty_query_no_vector_ranking`).
3. `QueryEmbeddingService` uses the same shared `TextEmbeddingProvider` as item indexing (`get_shared_text_embedding_provider`: production uses multilingual E5 1024-dim; unit tests default to `mock` via `TEXT_EMBEDDING_PROVIDER`).
4. Output validated with **`validate_provider_embedding_vector`** (identical contract as item path: length, finiteness, pack size).

Item embedding generation and query embedding generation are **separate classes** (`TextEmbeddingService` vs `QueryEmbeddingService`) sharing validation and provider types only.

## Vector search algorithm (application-side)

**Decision:** Phase 2 uses **Option A — application-side cosine similarity** over decoded `list[float]` from `Item.get_text_embedding()`. No pgvector in this phase.

- **Similarity:** cosine similarity in **[-1, 1]** (`app/domain/text_embedding_similarity.py`). L2-normalized mock/item vectors typically fall in **[0, 1]** for near-duplicates.
- **Eligibility:** only items passing **`listing_has_current_text_embedding`** are scored. Stale rows, missing hash, `semantic_text` mismatch, or corrupt binary are **skipped** (no silent trust of blobs).
- **Ordering:** after scoring, sort is **deterministic**: primary score descending, then `distance_km` ascending (missing distance last), then `item.id` ascending.

## Hybrid scoring formula

Let `lexical_01 = normalized_lexical_relevance(item, query)` in **[0, 1]** (exact normalized title match casefold = 1.0; title prefix / substring; else scaled keyword field hits mirroring `item_service` keyword weights).

Let `cosine` be cosine similarity in **[-1, 1]**. Map to **[0, 1]**:

`vec_01 = (cosine + 1) / 2`

Weights from settings (normalized to sum 1 if needed):

`hybrid_01 = w_lex * lexical_01 + w_vec * vec_01`

**Exact-title guard:** if `lexical_01 == 1.0`, then `hybrid_01 = max(hybrid_01, search_hybrid_exact_title_floor)` (default **0.92**) so high-precision lexical hits are not buried by weak vectors.

**Semantic mode:** items without a vector cosine are **removed** from the result set. Ranking uses `vec_01` only; `ranking_score` is `100 * vec_01` for API display.

**Hybrid mode:** items without embeddings remain in the list with **lexical-only** hybrid component (`text_hybrid_score = lexical_01` when cosine missing).

API `ranking_score` after hybrid/semantic rerank is **`100 * hybrid_01`** (or semantic equivalent) for comparability with legacy 0–100-ish scale.

Settings:

| Setting | Default | Role |
|---------|---------|------|
| `search_hybrid_lexical_weight` | 0.35 | `w_lex` |
| `search_hybrid_vector_weight` | 0.65 | `w_vec` |
| `search_hybrid_exact_title_floor` | 0.92 | floor when title exact match |
| `search_vector_candidate_cap` | 500 | max rows after geo filter before vector work |

## Candidate selection

1. Same **hard filters** as lexical search: `is_public`, discoverable statuses, geo (bbox + radius or bounds), category/domain/type/price/service_category, optional **lexical SQL filter** when `query` is set.
2. If `text_search_mode` is hybrid/semantic, query is non-empty, and the lexical-filtered set is **empty**, **one fallback query** runs **without** the text filter (still all other filters) to allow pure semantic recall within the geo window.
3. After Haversine (radius) or inclusion (bounds), if hybrid/semantic applies and `sort` is **not** `price_*`, `newest`, `oldest`, or `nearest`, the in-radius list is **truncated** to `search_vector_candidate_cap` by **`item.id` ascending** (deterministic cap — not a full-table scan).

4. **Defensive bound (rerank entry):** `maybe_apply_text_vector_ranking` **truncates again** to `search_vector_candidate_cap` (by `item.id`) if the caller ever passes a longer list. Vector cosine work therefore **cannot** exceed this cap per request, even if `item_service` regresses.

When `sort` is `nearest`, `price_*`, `newest`, or `oldest`, vector reranking is **skipped**; `text_search_fallback_reason` records `sort_<name>_lexical_only`.

## Acceptance tests (closure)

- **Hybrid ranking:** `TestHybridRankingAcceptance.test_exact_title_match_not_buried_by_better_vector_weaker_lexical` — item A has **exact title match** and an embedding **orthogonal** to a fixed query axis; item B has **weak lexical** (description-only keyword hit) and an embedding **aligned** with that axis. Asserts documented `compute_hybrid_score` ordering (`h_a > h_b`, title floor) and **`search_nearby_items`…`hybrid`** returns A first.
- **Candidate cap:** `TestVectorCandidateCapEnforced.test_search_nearby_truncates_pairs_before_hybrid_rerank` (integration) and `test_maybe_apply_defensive_cap_truncates_oversized_batch` (rerank guard).

## Execution verification

Run on **Python 3.11 or 3.12** with project-compatible SQLAlchemy (see `backend/requirements.txt`):

```bash
cd backend && pytest tests/test_text_embedding_hardening.py tests/test_text_vector_search_phase2.py -q
```

**Closure run:** Python **3.12.x**, command as above, **70 passed** (including `test_sentence_transformers_text_provider.py`) in Docker `python:3.12-slim-bookworm` with deps aligned to `requirements.txt` (see `REAL_TEXT_EMBEDDING_MODEL_REPORT.md`).

## Failure modes / fallback

| Condition | Behavior |
|-----------|----------|
| `enable_text_vector_search=false` | Lexical sort only; `text_search_fallback_reason=text_vector_search_disabled` |
| Empty normalized query | No embedding; lexical only; `empty_query_no_vector_ranking` |
| Provider / validation error | Lexical only; `query_embedding_failed:...` |
| Semantic mode, no items with embeddings | Empty result list for that page |
| Corrupt `get_text_embedding` | Item skipped for vector score |

## Limitations

- **Latency / memory:** up to `search_vector_candidate_cap` decode + dot products per request.
- **Mock provider** is non-semantic; quality is not representative of production sentence models.
- **Total_count** in hybrid/semantic reflects the **capped, reranked candidate set**, not a separate global SQL count.

## Future: pgvector

Keep packed blobs as source of truth; add a generated column or side table + `CREATE INDEX … USING ivfflat (embedding vector_cosine_ops)` later. Swap `TextVectorSearchService` internals to SQL `ORDER BY embedding <=> :query_vec` behind the same eligibility rules (fingerprint gate in SQL or post-filter). Business logic in `hybrid_search_service` should remain unchanged.
