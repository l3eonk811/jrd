"""
Application-side text vector similarity over Phase 1 packed item embeddings.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.domain.text_embedding_errors import CorruptedTextEmbeddingStorageError
from app.domain.text_embedding_similarity import cosine_similarity
from app.models.item import Item
from app.services.text_embedding_freshness import listing_has_current_text_embedding

logger = logging.getLogger(__name__)


class TextVectorSearchService:
    """Score items by cosine similarity between query vector and stored text embeddings."""

    def score_items_by_text_similarity(
        self,
        items: Iterable[Item],
        query_vector: List[float],
    ) -> Dict[int, float]:
        """
        Map item_id -> cosine similarity in [-1, 1].

        Skips items failing ``listing_has_current_text_embedding`` or corrupt binary reads.
        """
        out: Dict[int, float] = {}
        for item in items:
            if not listing_has_current_text_embedding(item):
                continue
            try:
                vec = item.get_text_embedding()
            except CorruptedTextEmbeddingStorageError:
                logger.warning("text_vector_search skip corrupt embedding item_id=%s", item.id)
                continue
            if vec is None:
                continue
            try:
                out[item.id] = cosine_similarity(query_vector, vec)
            except ValueError:
                continue
        return out
