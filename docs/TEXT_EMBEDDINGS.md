# Listing text embeddings (Phase 1 — hardened)

## What is `semantic_text`?

`semantic_text` is a **canonical, deterministic string** built from user-visible listing fields. It is **not** the raw database row; it is a normalized concatenation used as the **sole input** to the text embedding provider.

Segments (non-empty only), in order, separated by ` | `:

| Prefix | Source |
|--------|--------|
| `title:` | `items.title` |
| `category:` | `items.category` |
| `subcategory:` | `items.subcategory` |
| `tag:` | each tag name (deduped case-insensitively, sorted) |
| `service_category:` | `service_details.service_category` |
| `animal_type:` | `adoption_details.animal_type` |
| `description:` | `items.description` |

Each value is NFC-normalized, trimmed, and internal whitespace collapsed to single spaces.

**Invariant:** Same logical listing content → identical `semantic_text` (bitwise), regardless of ORM collection order for tags.

## Semantic text format version

`SEMANTIC_TEXT_FORMAT_VERSION` in `app/domain/text_embedding_constants.py` is part of the **stored freshness fingerprint** (`compute_embedding_source_fingerprint`), not of the visible `semantic_text` string. When `build_semantic_text` rules change in a breaking way, bump this constant so existing rows become stale (hash mismatch) without manual data fixes.

## Embedding lifecycle

1. **Build** `semantic_text` via `build_semantic_text(item)`.
2. **Fingerprint** with `compute_embedding_source_fingerprint(semantic_text)` → SHA-256 hex (64 chars), stored in `text_embedding_source_hash` after a successful embed (includes semantic format version, **vector dim** (`TEXT_EMBEDDING_DIM`), and normalized semantic content).
3. **Vector** from `TextEmbeddingProvider.embed_listing_text(semantic_text)` → validated to exactly **`TEXT_EMBEDDING_DIM`** (1024 for multilingual E5) finite `float32` values (`validate_provider_embedding_vector`), then packed **little-endian** via `Item.set_text_embedding` into `text_embedding` (`TEXT_EMBEDDING_DIM * 4` bytes).
4. **Timestamp** `text_embedding_updated_at` (UTC) is set **only** on successful commit of vector + `semantic_text` + fingerprint together.

**Stale-write guard:** After the provider returns, before any write, the job **expires** the `Item` in the session and rebuilds semantic text from the database. If it differs from the snapshot passed to `embed()`, the job returns `ABORTED_SOURCE_STALE` and **does not** persist the vector (prevents committing a vector computed from overwritten source). If another session changed a semantic column (e.g. title) concurrently, ORM invalidation may already have cleared `text_embedding`; the row then ends with **no** stored vector rather than a stale one.

**Clearing:** `Item.clear_listing_text_embedding()` nulls `text_embedding`, `semantic_text`, `text_embedding_source_hash`, `text_embedding_updated_at`. It does **not** touch `image_embedding`.

**Explicit queue:** `text_embedding_needs_reindex` (boolean) and `text_embedding_reindex_requested_at` (UTC) track rows that still need `python -m tools.index_text_embeddings` (no inline embed on create/update). See `TEXT_EMBEDDING_REINDEX_FLOW_REPORT.md` at repo root.

## Centralized invalidation (ORM)

`app/orm/text_embedding_listeners.py` registers SQLAlchemy listeners so **ordinary ORM writes** clear text embedding state when semantic sources change, without going through `item_service.update_item`, and **mark** `text_embedding_needs_reindex`:

- `Item.before_update` on `title`, `category`, `subcategory`, `description`
- `Session.before_flush` for `ItemTag` inserts/deletes (tag links) and for **`ServiceDetails.service_category`** / **`AdoptionDetails.animal_type`** changes on dirty detail rows (avoids clearing the parent `Item` from inside another mapper’s `before_update`, which SQLAlchemy can drop on flush)
- `ServiceDetails.after_insert` / `AdoptionDetails.after_insert` still clear on new detail rows

**Limitation:** SQLAlchemy **bulk** operations (`Query.delete()`, `bulk_update_mappings`, raw SQL `UPDATE`) **do not** emit these listeners. Those paths may leave **physical** blob/hash rows unchanged even when source columns drift.

Tag replacement in `update_item` uses per-row `db.delete(link)` on `ItemTag` so flushes participate in the same invalidation path.

## Runtime fingerprint gate (bulk-SQL safe)

ORM listeners handle **normal** invalidation. **No code path may treat a row as “has a current embedding” from a non-NULL blob alone.**

- **`listing_has_current_text_embedding(item)`** returns **True** only when: `text_embedding` and `text_embedding_source_hash` are both set, canonical `build_semantic_text(item)` is non-empty, the persisted **`items.semantic_text` equals that canonical string** (snapshot consistency), and `text_embedding_source_hash == compute_embedding_source_fingerprint(that semantic)`. Otherwise **False** — including after bulk/Core SQL changed source fields without clearing storage, or if the stored snapshot column was corrupted relative to live fields.

- **`listing_needs_text_embedding_index(item)`** drives indexer work: for non-empty canonical semantic it is **`not listing_has_current_text_embedding(item)`**; for empty canonical semantic it is **True** if any embedding residue remains (blob, hash, timestamp, or non-blank stored `semantic_text`).

- **`is_text_embedding_stale(item)`** is **True** iff a blob exists and **`not listing_has_current_text_embedding(item)`**; **False** if there is no blob.

The text embedding indexer, when **`not force`**, skips a row only when **`not listing_needs_text_embedding_index(item)`** (freshness gate — not blob presence).

`generate_text_embedding_for_item(..., force=False)` skips work only when **`listing_has_current_text_embedding(item)`** — same fingerprint rule, independent of listener side effects.

## Corrupted binary read policy

`Item.get_text_embedding()` **always** returns `None` if `text_embedding` IS NULL. If bytes are present but wrong length or unpack to non-finite floats, it **always** raises `CorruptedTextEmbeddingStorageError` (no silent `None`, no mixed logging paths). Callers must catch that exception or treat absent storage via `text_embedding is None` before read.

## Empty semantic invariant

**No** text embedding job may leave a **successful** stored vector or fingerprint when canonical `build_semantic_text(item)` is empty or whitespace-only:

- **No row state:** outcome `SKIPPED_EMPTY`; no DB writes.
- **Orphan / leftover metadata:** outcome `CLEARED_ORPHAN_EMBEDDING`; `clear_listing_text_embedding()` + commit when `commit=True`.

The provider still never receives empty input (`EmptySemanticTextInputError` on the provider layer); empty handling is enforced before `embed()`.

## Production provider (sentence-transformers)

When `TEXT_EMBEDDING_PROVIDER=sentence_transformers` (default in `app/config.py`; tests force `mock` via `conftest.py`):

- **Model:** `TEXT_EMBEDDING_MODEL_NAME` (default `intfloat/multilingual-e5-large`, 1024-dim, Arabic-capable).
- **Prefixes:** listing text uses `passage: ` + `semantic_text`; search queries use `query: ` + normalized query (E5 retrieval convention).
- **Load:** lazy, one process-wide singleton; `TEXT_EMBEDDING_DEVICE`: `cpu`, `cuda`, or `auto`.

## Mock provider (`TEXT_EMBEDDING_PROVIDER=mock`)

`MockTextEmbeddingProvider`:

- **Deterministic** for identical `semantic_text`.
- **Non-semantic:** does not encode meaning, synonyms, or ranking quality.
- **Not for evaluation** of search relevance — infrastructure / plumbing only.
- Implementation reads **`shake_256(...).digest(dim * 4)`** in one call so each dimension gets distinct XOF output; repeated `digest(4)` on CPython’s `HASHXOF` does not advance the stream and would collapse distinct inputs to the same L2 direction.

Output is still validated by `validate_provider_embedding_vector` before persistence (`dim` must match `TEXT_EMBEDDING_DIM`).

## Reindex workflow

From `backend/`:

```bash
python -m tools.index_text_embeddings
python -m tools.index_text_embeddings --force
python -m tools.index_text_embeddings --start-id 1 --limit 1000 --batch-size 50
```

- Without `--force`: skips rows where `listing_needs_text_embedding_index` is false (fingerprint gate — not blob presence); see **Runtime fingerprint gate** above.
- With `--force`: recomputes vector and fingerprint even if current.
- Outcomes `CLEARED_ORPHAN_EMBEDDING` and `ABORTED_SOURCE_STALE` appear in per-run stats (`cleared_empty`, `aborted_stale`) and in the `outcomes` breakdown dict.
- Ordering: `id ASC`. Batched `joinedload` to avoid N+1.

Apply DB migrations before first run:

```bash
alembic upgrade head
```

## Operational caveats

- **Dimension lock:** `TEXT_EMBEDDING_DIM` in `app/domain/text_embedding_constants.py` (1024 for current E5). Changing it requires a coordinated migration, fingerprint invalidation, and reindex. See Alembic `0032_clear_text_embeddings_for_1024_dim.py` for the 384→1024 transition pattern.
- **Image pipeline:** `embedding_service.py` / `image_embedding` are unrelated; do not store text vectors there.
- **PostgreSQL vs tests:** CI/tests use SQLite via `Base.metadata.create_all`; production uses Alembic migrations.
- **Failures:** Indexer logs `item_id`, `outcome`, and `detail` per row; one failure does not stop the batch. Provider validation failures do not mutate the item row.

## API surface

Phase 1 **does not** require HTTP consumers to use embeddings. Optional Phase 2 discover search uses them; see `docs/TEXT_VECTOR_SEARCH.md`.
