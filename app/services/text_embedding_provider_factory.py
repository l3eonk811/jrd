"""
Process-wide text embedding provider (mock or sentence-transformers).

Use ``get_shared_text_embedding_provider()`` from services instead of constructing
``MockTextEmbeddingProvider`` in application code so tests and production share one entrypoint.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.sentence_transformers_text_provider import get_sentence_transformers_e5_singleton
from app.services.text_embedding_providers import MockTextEmbeddingProvider, TextEmbeddingProvider


@lru_cache(maxsize=1)
def get_shared_text_embedding_provider() -> TextEmbeddingProvider:
    s = get_settings()
    kind = (s.text_embedding_provider or "mock").lower().strip()
    if kind == "mock":
        return MockTextEmbeddingProvider()
    if kind == "sentence_transformers":
        return get_sentence_transformers_e5_singleton(
            model_name=s.text_embedding_model_name,
            device=s.text_embedding_device,
        )
    raise ValueError(
        f"Unknown TEXT_EMBEDDING_PROVIDER={kind!r}; expected 'mock' or 'sentence_transformers'."
    )


def clear_text_embedding_provider_cache_for_tests() -> None:
    """Reset factory cache (pytest or settings override)."""
    get_shared_text_embedding_provider.cache_clear()
