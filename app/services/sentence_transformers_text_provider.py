"""
Sentence-transformers backend for listing text embeddings (E5 family).

Arabic-capable default: intfloat/multilingual-e5-large (1024-dim).

Not used for image embeddings; separate from ``embedding_service`` / OpenCLIP.
"""

from __future__ import annotations

import logging
import threading
from typing import List

from app.domain.text_embedding_constants import TEXT_EMBEDDING_DIM
from app.domain.text_embedding_errors import EmptySemanticTextInputError
from app.services.text_embedding_providers import TextEmbeddingProvider

logger = logging.getLogger(__name__)

_load_lock = threading.Lock()
_singleton: "SentenceTransformersE5Provider | None" = None


def get_sentence_transformers_e5_singleton(
    model_name: str,
    device: str,
) -> "SentenceTransformersE5Provider":
    """One shared model per process (heavy GPU/CPU memory)."""
    global _singleton
    with _load_lock:
        if _singleton is None:
            _singleton = SentenceTransformersE5Provider(model_name=model_name, device=device)
        elif (
            _singleton._model_name != model_name
            or _singleton._device_setting != device
        ):
            raise RuntimeError(
                "SentenceTransformersE5Provider already loaded with different "
                f"model_name={_singleton._model_name!r} device={_singleton._device_setting!r}; "
                "process restart required to change TEXT_EMBEDDING_MODEL_NAME / TEXT_EMBEDDING_DEVICE."
            )
        return _singleton


class SentenceTransformersE5Provider(TextEmbeddingProvider):
    """
    Multilingual E5 (e.g. intfloat/multilingual-e5-large) with retrieval prefixes.

    Uses ``passage:`` for listing semantic text and ``query:`` for search queries
    (recommended for asymmetric retrieval; same model for both encoders).
    """

    dim: int = TEXT_EMBEDDING_DIM

    def __init__(self, *, model_name: str, device: str = "cpu") -> None:
        self._model_name = model_name.strip()
        self._device_setting = (device or "cpu").strip()
        self._model = None
        self._resolved_device: str | None = None

    def _resolve_device(self) -> str:
        d = self._device_setting.lower()
        if d == "auto":
            try:
                import torch

                return "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                return "cpu"
        return self._device_setting

    def _lazy_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers is required when TEXT_EMBEDDING_PROVIDER=sentence_transformers. "
                "Install backend dependencies (see requirements.txt) or set TEXT_EMBEDDING_PROVIDER=mock."
            ) from e

        resolved = self._resolve_device()
        self._resolved_device = resolved
        logger.info(
            "loading_sentence_transformer model=%s device=%s",
            self._model_name,
            resolved,
        )
        try:
            model = SentenceTransformer(self._model_name, device=resolved)
        except Exception as e:
            logger.exception("sentence_transformer_load_failed model=%s", self._model_name)
            raise RuntimeError(
                f"Failed to load text embedding model {self._model_name!r} on {resolved!r}: "
                f"{type(e).__name__}: {e}"
            ) from e

        mdim = int(model.get_sentence_embedding_dimension())
        if mdim != TEXT_EMBEDDING_DIM:
            raise RuntimeError(
                f"Model {self._model_name!r} reports embedding dimension {mdim}, "
                f"but TEXT_EMBEDDING_DIM is {TEXT_EMBEDDING_DIM}. "
                "Update text_embedding_constants or choose a matching model."
            )
        self._model = model
        return self._model

    def embed(self, text: str) -> List[float]:
        return self.embed_listing_text(text)

    def embed_listing_text(self, text: str) -> List[float]:
        normalized = (text or "").strip()
        if not normalized:
            raise EmptySemanticTextInputError("empty text for passage embedding")
        return self._encode_prefixed("passage: ", normalized)

    def embed_search_query(self, text: str) -> List[float]:
        normalized = (text or "").strip()
        if not normalized:
            raise EmptySemanticTextInputError("empty text for query embedding")
        return self._encode_prefixed("query: ", normalized)

    def _encode_prefixed(self, prefix: str, normalized: str) -> List[float]:
        model = self._lazy_model()
        full = f"{prefix}{normalized}"
        try:
            vec = model.encode(
                full,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as e:
            logger.exception("sentence_transformer_encode_failed")
            raise RuntimeError(
                f"Text embedding encode failed: {type(e).__name__}: {e}"
            ) from e

        out = list(vec.astype("float64").flatten().tolist())
        if len(out) != TEXT_EMBEDDING_DIM:
            raise RuntimeError(
                f"encode returned length {len(out)}, expected {TEXT_EMBEDDING_DIM}"
            )
        return out
