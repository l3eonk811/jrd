"""
Domain-specific errors for listing text embeddings (never generic ValueError for contracts).

**Corrupted persisted reads:** ``Item.get_text_embedding()`` returns ``None`` only when
``text_embedding`` is NULL. Wrong byte length or non-finite unpacked values always raise
``CorruptedTextEmbeddingStorageError`` (no alternate ``None`` + log path).
"""


class TextEmbeddingDomainError(Exception):
    """Base for text-embedding storage and validation failures."""


class InvalidTextEmbeddingVectorError(TextEmbeddingDomainError):
    """Vector rejected before persistence (None, wrong length, non-finite, non-numeric)."""


class CorruptedTextEmbeddingStorageError(TextEmbeddingDomainError):
    """Persisted binary is missing, wrong length, or unpacks to non-finite floats."""


class EmptySemanticTextInputError(TextEmbeddingDomainError):
    """Provider refused empty / whitespace-only semantic input (no embedding produced)."""
