"""
Query-side text embedding for vector search (Phase 2).

Separate from ``TextEmbeddingService`` / item indexing: same dimension and validation,
different responsibility and entrypoint.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.domain.text_embedding_constants import TEXT_EMBEDDING_DIM
from app.domain.text_embedding_errors import EmptySemanticTextInputError, InvalidTextEmbeddingVectorError
from app.services.semantic_text import normalize_free_text_for_embedding_query
from app.services.text_embedding_provider_factory import get_shared_text_embedding_provider
from app.services.text_embedding_providers import TextEmbeddingProvider
from app.services.text_embedding_service import validate_provider_embedding_vector

logger = logging.getLogger(__name__)


class QueryEmbeddingService:
    """Embed normalized search queries using a ``TextEmbeddingProvider`` (shared factory)."""

    def __init__(self, provider: Optional[TextEmbeddingProvider] = None) -> None:
        self._provider = provider or get_shared_text_embedding_provider()
        if self._provider.dim != TEXT_EMBEDDING_DIM:
            raise InvalidTextEmbeddingVectorError(
                f"query provider dim {self._provider.dim} != TEXT_EMBEDDING_DIM {TEXT_EMBEDDING_DIM}"
            )

    @property
    def provider(self) -> TextEmbeddingProvider:
        return self._provider

    def embed_query_vector(self, raw_query: str) -> List[float]:
        """
        Return a validated ``TEXT_EMBEDDING_DIM`` float list for ``raw_query``.

        Raises:
            EmptySemanticTextInputError: whitespace-only or empty after normalization.
            InvalidTextEmbeddingVectorError: provider contract violation.
        """
        normalized = normalize_free_text_for_embedding_query(raw_query)
        if not normalized:
            raise EmptySemanticTextInputError("query is empty or whitespace-only after normalization")
        try:
            vec = self._provider.embed_search_query(normalized)
        except EmptySemanticTextInputError:
            raise
        except Exception as e:
            logger.exception("query_embedding provider failure")
            raise InvalidTextEmbeddingVectorError(f"query embed failed: {type(e).__name__}: {e}") from e
        validate_provider_embedding_vector(vec)
        return vec
