"""
Single source of truth for listing text embedding dimensions and storage layout.

All pack/unpack and provider output MUST match these values exactly.
"""

# intfloat/multilingual-e5-large (and -instruct) use 1024-dim sentence embeddings.
TEXT_EMBEDDING_DIM: int = 1024

# Bump when ``build_semantic_text`` / segment rules change so old hashes invalidate.
SEMANTIC_TEXT_FORMAT_VERSION: int = 1

# float32 little-endian per field; total bytes for one stored vector
TEXT_EMBEDDING_PACKED_BYTES: int = TEXT_EMBEDDING_DIM * 4

# struct.pack format: little-endian IEEE 754 binary32 × DIM (explicit endianness)
TEXT_EMBEDDING_STRUCT_FMT: str = f"<{TEXT_EMBEDDING_DIM}f"
