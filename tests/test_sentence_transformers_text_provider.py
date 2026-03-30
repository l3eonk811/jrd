"""Sentence-transformers E5 provider contract (mocked model; no HF download)."""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import MagicMock

import numpy as np

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.domain.text_embedding_constants import TEXT_EMBEDDING_DIM
from app.models.item import Item
from app.services.sentence_transformers_text_provider import SentenceTransformersE5Provider


def test_e5_provider_uses_passage_and_query_prefixes():
    mock_model = MagicMock()
    seen: list[str] = []

    def encode_side_effect(s, **kwargs):
        seen.append(s)
        v = np.zeros(TEXT_EMBEDDING_DIM, dtype=np.float32)
        v[0] = 1.0
        return v

    mock_model.encode.side_effect = encode_side_effect
    mock_model.get_sentence_embedding_dimension.return_value = TEXT_EMBEDDING_DIM

    p = SentenceTransformersE5Provider(model_name="intfloat/multilingual-e5-large", device="cpu")
    p._model = mock_model  # type: ignore[attr-defined]

    p.embed_listing_text("مرحبا بالعالم")
    p.embed_search_query("بحث تجريبي")

    assert any(x.startswith("passage: ") for x in seen)
    assert any(x.startswith("query: ") for x in seen)
    assert len(seen) == 2


def test_e5_output_length_matches_constant():
    mock_model = MagicMock()
    mock_model.encode.return_value = np.ones(TEXT_EMBEDDING_DIM, dtype=np.float32)
    mock_model.get_sentence_embedding_dimension.return_value = TEXT_EMBEDDING_DIM

    p = SentenceTransformersE5Provider(model_name="x", device="cpu")
    p._model = mock_model  # type: ignore[attr-defined]

    out = p.embed_listing_text("test")
    assert len(out) == TEXT_EMBEDDING_DIM


def test_text_embedding_column_independent_from_image_embedding():
    it = Item()
    assert hasattr(it, "text_embedding")
    assert hasattr(it, "image_embedding")
    assert it.text_embedding is None and it.image_embedding is None
