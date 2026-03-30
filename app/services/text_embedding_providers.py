"""
Pluggable text embedding providers (listing semantics only; not OpenCLIP).

The mock provider is **non-semantic**: deterministic pseudo-random vectors from a hash stream.
It must never be used to claim retrieval quality or synonym understanding.
"""

from __future__ import annotations

import hashlib
import logging
import math
import struct
from abc import ABC, abstractmethod
from typing import List

from app.domain.text_embedding_constants import TEXT_EMBEDDING_DIM
from app.domain.text_embedding_errors import EmptySemanticTextInputError

logger = logging.getLogger(__name__)


class TextEmbeddingProvider(ABC):
    """
    Contract: ``embed`` should return exactly ``TEXT_EMBEDDING_DIM`` finite floats.

    Implementations may violate this; ``validate_provider_embedding_vector`` enforces the
    contract before any database write.

    Listing vs query paths: E5 models use ``passage:`` / ``query:`` prefixes; defaults
    delegate to ``embed`` so mocks and legacy tests keep a single implementation.
    """

    dim: int = TEXT_EMBEDDING_DIM

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Return L2-normalized vector for non-empty ``text`` (listing-oriented default)."""

    def embed_listing_text(self, text: str) -> List[float]:
        """Canonical listing/document embedding input (E5: ``passage:`` prefix)."""
        return self.embed(text)

    def embed_search_query(self, text: str) -> List[float]:
        """Search-query embedding (E5: ``query:`` prefix)."""
        return self.embed(text)

    @property
    def name(self) -> str:
        return self.__class__.__name__


class MockTextEmbeddingProvider(TextEmbeddingProvider):
    """
    Deterministic, **non-semantic** embedding for infrastructure only.

    Algorithm: SHAKE-256 stream over UTF-8 text → big-endian uint32 chunks → float in [-1,1] → L2 normalize.
    Identical input → identical output (bitwise float sequence). Not suitable for semantic evaluation.
    """

    def embed(self, text: str) -> List[float]:
        normalized = (text or "").strip()
        if not normalized:
            raise EmptySemanticTextInputError("mock provider refuses empty semantic text")

        shake = hashlib.shake_256(normalized.encode("utf-8"))
        # One XOF read of dim×4 bytes — repeated digest(4) does not advance the stream
        # on CPython 3.11+ (_hashlib.HASHXOF), which would collapse every input to the
        # same L2 direction and break determinism/distinguishability tests.
        blob = shake.digest(self.dim * 4)
        vec: List[float] = []
        for i in range(self.dim):
            chunk = blob[i * 4 : i * 4 + 4]
            u = struct.unpack("!I", chunk)[0]
            vec.append((u / 2**32) * 2.0 - 1.0)

        norm = math.sqrt(sum(x * x for x in vec))
        if norm < 1e-12:
            logger.error(
                "mock_text_embedding degenerate_norm provider=%s dim=%s",
                self.name,
                self.dim,
            )
            raise RuntimeError("mock embedding degenerate norm (non-finite pipeline)")
        out = [x / norm for x in vec]
        for i, f in enumerate(out):
            if not math.isfinite(f):
                raise RuntimeError(f"mock embedding produced non-finite at index {i}")
        return out
