"""
Cosine similarity for Phase 1 text embedding vectors (``TEXT_EMBEDDING_DIM`` float32 lists).

Same metric regardless of storage packing: callers pass decoded ``list[float]``.
"""

from __future__ import annotations

import math
from typing import Sequence


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Cosine similarity in [-1.0, 1.0].

    For L2-normalized unit vectors (mock + successful item embeddings), equals dot product
    and typically lies in [0, 1] for similar-looking listing text.
    """
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
